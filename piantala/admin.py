from collections import defaultdict
from importlib.metadata import PackageNotFoundError, distributions, version as package_version
import json
from pathlib import Path
import platform
import shutil
import sys

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .home_assistant import HomeAssistantError, sync_entity_catalog, test_connection
from .extensions import db
from .forms import (
    ActionForm,
    ActivityTypeForm,
    CultivationTypeForm,
    CultivationTypeImageForm,
    CultivationTypeVariantForm,
    DeleteForm,
    HomeAssistantSettingsForm,
    PlatformSettingsForm,
    LinkTypeForm,
    ManagedMdiIconAddForm,
    MarkerColorForm,
    SMTP_PROVIDER_DEFAULTS,
    SiteInviteForm,
    UserForm,
)
from .mailing import MailError, send_email
from .media import Image, relative_upload_to_fs_path
from .models import (
    ActivityType,
    AuthToken,
    CultivationType,
    CultivationTypeImage,
    CultivationTypeVariant,
    GardenSettings,
    HomeAssistantEntityCatalog,
    HomeAssistantSettings,
    LinkType,
    ManagedMdiIcon,
    MarkerColor,
    NodeActivity,
    NodeActivityImage,
    NodeExternalLink,
    NodePhoto,
    GardenNode,
    Role,
    PlatformSettings,
    SiteMembership,
    TranslationEntry,
    User,
)
from .site_context import current_site, require_current_site
from .utils import permission_required, save_uploaded_file
from .translations import DEFAULT_LOCALE, SUPPORTED_LOCALES


bp = Blueprint("admin", __name__, url_prefix="/admin")

MDI_METADATA_URLS = [
    "https://cdn.jsdelivr.net/npm/@mdi/svg@7.4.47/meta.json",
    "https://unpkg.com/@mdi/svg@7.4.47/meta.json",
]


def _build_external_url(endpoint: str, **values) -> str:
    """Return one public URL for admin-triggered emails.

    Parameters:
        endpoint: Flask endpoint name.
        **values: URL variables forwarded to ``url_for``.
    """
    from urllib.parse import urljoin

    platform_settings = PlatformSettings.get_or_create()
    absolute = url_for(endpoint, _external=True, **values)
    if not platform_settings.public_base_url:
        return absolute
    relative = url_for(endpoint, _external=False, **values)
    return urljoin(platform_settings.public_base_url.rstrip("/") + "/", relative.lstrip("/"))


def _marker_icon_choices(selected_icon: str | None = None) -> list[tuple[str, str]]:
    """Return cultivation-type icon choices, preserving an existing custom icon.

    Parameters:
        selected_icon: Existing saved icon value that should stay selectable.
    """
    normalized_selected_icon = _normalized_marker_icon(selected_icon)
    choices = [("", "No icon")] + [
        (icon.icon_name_normalized, icon.icon_name_normalized)
        for icon in ManagedMdiIcon.query.order_by(ManagedMdiIcon.icon_name).all()
        if icon.icon_name_normalized
    ]
    if normalized_selected_icon and all(value != normalized_selected_icon for value, _label in choices):
        choices.append((normalized_selected_icon, normalized_selected_icon))
    return choices


def _normalized_marker_icon(value: str | None) -> str | None:
    """Normalize an optional MDI icon to ``mdi-*`` form.

    Parameters:
        value: Raw icon value coming from a form field.
    """
    icon = (value or "").strip()
    if not icon:
        return None
    if not icon.startswith("mdi-"):
        return f"mdi-{icon}"
    return icon


def _mdi_icon_usage_rows(icon_name: str) -> list[dict[str, str | int]]:
    """Return every place where one managed MDI icon is used.

    Parameters:
        icon_name: Normalized ``mdi-*`` icon name to inspect.
    """
    rows: list[dict[str, str | int]] = []

    for cultivation_type in CultivationType.query.order_by(
        CultivationType.botanical_name,
        CultivationType.common_name,
        CultivationType.id,
    ).all():
        if cultivation_type.default_marker_icon_normalized != icon_name:
            continue
        rows.append(
            {
                "kind": "cultivation_type",
                "label": cultivation_type.selector_label or cultivation_type.default_node_title or icon_name,
                "detail": "Cultivation type default icon",
                "url": url_for("admin.edit_cultivation_type", cultivation_type_id=cultivation_type.id),
                "id": cultivation_type.id,
            }
        )

    for variant in CultivationTypeVariant.query.order_by(
        CultivationTypeVariant.cultivation_type_id,
        CultivationTypeVariant.sort_order,
        CultivationTypeVariant.name,
        CultivationTypeVariant.id,
    ).all():
        if _normalized_marker_icon(variant.default_marker_icon) != icon_name:
            continue
        rows.append(
            {
                "kind": "cultivation_variant",
                "label": f"{variant.cultivation_type.selector_label}: {variant.name}",
                "detail": "Legacy variant icon",
                "url": url_for("admin.edit_cultivation_type_variant", variant_id=variant.id),
                "id": variant.id,
            }
        )

    for node in GardenNode.query.order_by(
        GardenNode.title,
        GardenNode.id,
    ).all():
        if _normalized_marker_icon(node.marker_icon) != icon_name:
            continue
        breadcrumb = " / ".join(crumb.title for crumb in node.breadcrumbs())
        rows.append(
            {
                "kind": "node",
                "label": node.title,
                "detail": breadcrumb,
                "url": url_for("main.node_detail", node_id=node.id),
                "id": node.id,
            }
        )

    return rows


def _apply_cultivation_type_marker_defaults(cultivation_type: CultivationType) -> int:
    """Rewrite node marker color/icon from cultivation type and variant defaults.

    Parameters:
        cultivation_type: Cultivation type whose linked cultivation nodes should be updated.
    """
    updated_count = 0
    for node in cultivation_type.nodes:
        variant = node.cultivation_type_variant
        default_color = (
            variant.effective_default_marker_color
            if variant is not None
            else cultivation_type.default_marker_color
        )
        default_icon = (
            variant.effective_default_marker_icon_normalized
            if variant is not None
            else cultivation_type.default_marker_icon_normalized
        )

        changed = False
        if default_color is not None and node.marker_color_id != default_color.id:
            node.marker_color = default_color
            node.hotspot_color = default_color.hex_value
            changed = True
        if default_icon is not None and node.marker_icon != default_icon:
            node.marker_icon = default_icon
            changed = True
        if changed:
            updated_count += 1
    return updated_count


def _format_bytes(size_in_bytes: int | None) -> str:
    """Return a human-readable file size string.

    Parameters:
        size_in_bytes: Raw size in bytes.
    """
    if size_in_bytes is None:
        return "Unknown"
    size = float(size_in_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_in_bytes} B"


def _sqlite_database_path() -> Path | None:
    """Return the local SQLite database path when Piantala is using SQLite."""
    database_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    prefix = "sqlite:///"
    if not database_uri.startswith(prefix):
        return None
    return Path(database_uri.removeprefix(prefix))


def _upload_directory() -> Path:
    """Return the absolute upload directory configured for Piantala."""
    return Path(current_app.config["UPLOAD_FOLDER"])


def _upload_relative_path(file_path: Path) -> str:
    """Convert an absolute upload file path to the stored relative image path.

    Parameters:
        file_path: Absolute file path inside the configured upload directory.
    """
    return f"uploads/{file_path.relative_to(_upload_directory()).as_posix()}"


def _upload_folder_path(file_path: Path) -> str:
    """Return the logical upload folder for one absolute upload file.

    Parameters:
        file_path: Absolute upload file path inside the configured upload directory.
    """
    relative_parent = file_path.parent.relative_to(_upload_directory()).as_posix()
    return relative_parent or "."


def _upload_directory_size(upload_dir: Path) -> int:
    """Calculate the total size of all files stored in the upload directory.

    Parameters:
        upload_dir: Absolute upload directory to inspect.
    """
    total_size = 0
    if not upload_dir.exists():
        return total_size
    for file_path in upload_dir.rglob("*"):
        if file_path.is_file():
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue
    return total_size


def _normalized_optional_text(value: str | None) -> str | None:
    """Return a trimmed text value or None when it is empty.

    Parameters:
        value: Raw text value collected from forms or database rows.
    """
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalized_optional_key(value: str | None) -> str | None:
    """Return a trimmed case-insensitive key for cultivation-type matching.

    Parameters:
        value: Raw text value collected from forms or database rows.
    """
    cleaned = _normalized_optional_text(value)
    return cleaned.casefold() if cleaned else None


def _cultivation_type_signature(
    botanical_name: str | None,
    common_name: str | None,
    life_cycle: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Return the normalized signature used to deduplicate cultivation types.

    Parameters:
        botanical_name: Botanical cultivation name.
        common_name: Common cultivation name.
        life_cycle: Annual/perennial value, when defined.
    """
    return (
        _normalized_optional_key(botanical_name),
        _normalized_optional_key(common_name),
        _normalized_optional_key(life_cycle),
    )


def _runtime_package_version(distribution_name: str) -> str:
    """Return the installed version for one Python distribution name.

    Parameters:
        distribution_name: Distribution name as registered in Python metadata.
    """
    try:
        return package_version(distribution_name)
    except PackageNotFoundError:
        return "not installed"


def _image_dimensions(file_path: Path) -> str:
    """Return one image size label like `1920 x 1080 px` when readable.

    Parameters:
        file_path: Absolute image file path to inspect.
    """
    if Image is None or not file_path.exists():
        return ""
    try:
        with Image.open(file_path) as image:
            return f"{image.width} x {image.height} px"
    except Exception:
        return ""


def _image_usage_map() -> dict[str, list[dict[str, str]]]:
    """Collect upload usage references grouped by stored relative image path."""
    usage_map: dict[str, list[dict[str, str]]] = defaultdict(list)

    settings = GardenSettings.get_or_create()
    if settings.map_image_path:
        usage_map[settings.map_image_path].append(
            {
                "label": "Garden map image",
                "target": url_for("main.map_settings"),
            }
        )

    for node in GardenNode.query.order_by(GardenNode.title).all():
        if node.hero_image_path:
            usage_map[node.hero_image_path].append(
                {
                    "label": f"{node.level_label} display image · {node.title}",
                    "target": url_for("main.node_detail", node_id=node.id),
                }
            )
        if node.map_image_path:
            usage_map[node.map_image_path].append(
                {
                    "label": f"{node.level_label} map image · {node.title}",
                    "target": url_for("main.node_detail", node_id=node.id),
                }
            )

    for photo in NodePhoto.query.join(GardenNode).order_by(NodePhoto.id).all():
        usage_map[photo.image_path].append(
            {
                "label": f"{photo.node.level_label} photo · {photo.node.title}",
                "target": url_for("main.node_detail", node_id=photo.node_id),
            }
        )

    for image in NodeActivityImage.query.join(NodeActivity).join(GardenNode).order_by(NodeActivityImage.id).all():
        usage_map[image.image_path].append(
            {
                "label": f"Activity image · {image.activity.node.level_label} · {image.activity.node.title}",
                "target": url_for("main.node_detail", node_id=image.activity.node_id),
            }
        )

    for image in CultivationTypeImage.query.join(CultivationType).order_by(CultivationTypeImage.id).all():
        usage_map[image.image_path].append(
            {
                "label": f"Cultivation type image · {image.cultivation_type.selector_label}",
                "target": url_for("admin.edit_cultivation_type", cultivation_type_id=image.cultivation_type_id),
            }
        )

    return usage_map


def _upload_inventory(folder: str | None = None, *, unused_only: bool = False) -> list[dict[str, object]]:
    """Build a detailed inventory of upload files and where each file is used.

    Parameters:
        folder: Optional upload subfolder filter such as `nodes/12`.
        unused_only: When True, keep only files without any usage reference.
    """
    upload_dir = _upload_directory()
    usage_map = _image_usage_map()
    inventory: list[dict[str, object]] = []
    seen_relative_paths: set[str] = set()
    folder_filter = folder.strip("/") if folder else None

    if upload_dir.exists():
        for file_path in sorted(
            [path for path in upload_dir.rglob("*") if path.is_file()],
            key=lambda path: path.stat().st_size,
            reverse=True,
        ):
            relative_path = _upload_relative_path(file_path)
            folder_path = _upload_folder_path(file_path)
            if folder_filter is not None and folder_path != folder_filter:
                continue
            seen_relative_paths.add(relative_path)
            file_size = file_path.stat().st_size
            usages = usage_map.get(relative_path, [])
            if unused_only and usages:
                continue
            inventory.append(
                {
                    "folder_path": folder_path,
                    "relative_path": relative_path,
                    "size_bytes": file_size,
                    "size_label": _format_bytes(file_size),
                    "dimension_label": _image_dimensions(file_path),
                    "usages": usages,
                    "missing": False,
                }
            )

    for relative_path, usages in usage_map.items():
        if relative_path in seen_relative_paths:
            continue
        folder_path = str(Path(relative_path.removeprefix("uploads/")).parent)
        if folder_path == ".":
            folder_path = "."
        if folder_filter is not None and folder_path != folder_filter:
            continue
        if unused_only and usages:
            continue
        inventory.append(
            {
                "folder_path": folder_path,
                "relative_path": relative_path,
                "size_bytes": None,
                "size_label": _format_bytes(None),
                "dimension_label": "",
                "usages": usages,
                "missing": True,
            }
        )

    inventory.sort(
        key=lambda item: (
            item["size_bytes"] is None,
            -(item["size_bytes"] or 0),
            str(item["relative_path"]).lower(),
        )
    )
    return inventory


def _upload_folder_inventory() -> list[dict[str, object]]:
    """Return upload folders with aggregated size and file counts."""
    folder_map: dict[str, dict[str, object]] = {}
    for item in _upload_inventory():
        folder_path = str(item["folder_path"])
        folder_entry = folder_map.setdefault(
            folder_path,
            {
                "folder_path": folder_path,
                "total_size_bytes": 0,
                "total_size_label": "0 B",
                "file_count": 0,
                "unused_count": 0,
            },
        )
        folder_entry["file_count"] = int(folder_entry["file_count"]) + 1
        folder_entry["total_size_bytes"] = int(folder_entry["total_size_bytes"]) + int(item["size_bytes"] or 0)
        if not item["usages"]:
            folder_entry["unused_count"] = int(folder_entry["unused_count"]) + 1

    folders = list(folder_map.values())
    for folder in folders:
        folder["total_size_label"] = _format_bytes(int(folder["total_size_bytes"]))
    folders.sort(key=lambda entry: str(entry["folder_path"]).lower())
    return folders


def _delete_upload_file(relative_path: str) -> bool:
    """Delete one physical upload file when it is no longer referenced.

    Parameters:
        relative_path: Stored relative `uploads/...` path.
    """
    usage_map = _image_usage_map()
    if usage_map.get(relative_path):
        return False
    file_path = relative_upload_to_fs_path(_upload_directory(), relative_path)
    try:
        if file_path.exists():
            file_path.unlink()
            return True
    except OSError:
        return False
    return False


def _link_type_name_values(link_type: LinkType | None = None) -> dict[str, str]:
    """Collect localized link-type names from the form or an existing record.

    Parameters:
        link_type: Existing link type being edited, if any.
    """
    values: dict[str, str] = {}
    for locale, _label in SUPPORTED_LOCALES:
        field_name = f"name_{locale}"
        if request.method == "POST":
            values[locale] = (request.form.get(field_name) or "").strip()
        elif link_type is not None:
            values[locale] = link_type.localized_name(locale)
        else:
            values[locale] = ""
    return values


def _link_type_name_errors(names_by_locale: dict[str, str]) -> dict[str, str]:
    """Validate that every configured locale has a link-type name.

    Parameters:
        names_by_locale: Localized names keyed by locale code.
    """
    errors: dict[str, str] = {}
    for locale, label in SUPPORTED_LOCALES:
        if not names_by_locale.get(locale):
            errors[locale] = f"Enter a name in {label}."
    return errors


@bp.route("/")
@login_required
def index():
    """Render the admin landing page for authorized users."""
    if current_user.has_permission("manage_users") or current_user.has_permission("manage_content"):
        return render_template(
            "admin_index.html",
            settings=GardenSettings.get_or_create(),
            ha_settings=HomeAssistantSettings.get_or_create(),
        )
    flash("You do not have permission for that action.", "danger")
    return redirect(url_for("main.index"))


@bp.route("/mdi-icons", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def mdi_icons():
    """Manage the curated MDI icon catalog used by Piantala."""
    add_form = ManagedMdiIconAddForm()
    delete_form = DeleteForm()

    if add_form.validate_on_submit():
        normalized_icon_name = _normalized_marker_icon(add_form.icon_name.data)
        if normalized_icon_name is None:
            flash("Choose one icon from the MDI catalog first.", "danger")
            return redirect(url_for("admin.mdi_icons"))

        icon = ManagedMdiIcon.query.filter_by(icon_name=normalized_icon_name).first()
        if icon is None:
            icon = ManagedMdiIcon(
                icon_name=normalized_icon_name,
                tags_json=add_form.tags_json.data or None,
            )
            db.session.add(icon)
            db.session.commit()
            flash("Icon added to the Piantala catalog.", "success")
        else:
            if not icon.tags_json and (add_form.tags_json.data or "").strip():
                icon.tags_json = add_form.tags_json.data
                db.session.commit()
            flash("That icon is already in the Piantala catalog.", "warning")
        return redirect(url_for("admin.mdi_icons"))

    icons = ManagedMdiIcon.query.order_by(ManagedMdiIcon.icon_name).all()
    usage_counts = {
        icon.id: len(_mdi_icon_usage_rows(icon.icon_name_normalized))
        for icon in icons
    }
    return render_template(
        "mdi_icons.html",
        settings=GardenSettings.get_or_create(),
        mdi_metadata_urls=MDI_METADATA_URLS,
        icons=icons,
        usage_counts=usage_counts,
        add_form=add_form,
        delete_form=delete_form,
    )


@bp.route("/mdi-icons/<int:icon_id>/usage", methods=["GET"])
@login_required
@permission_required("manage_content")
def mdi_icon_usage(icon_id: int):
    """Show where one managed MDI icon is currently used."""
    icon = ManagedMdiIcon.query.get_or_404(icon_id)
    return render_template(
        "mdi_icon_usage.html",
        settings=GardenSettings.get_or_create(),
        icon=icon,
        usage_rows=_mdi_icon_usage_rows(icon.icon_name_normalized),
    )


@bp.route("/mdi-icons/<int:icon_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_mdi_icon(icon_id: int):
    """Remove one icon from the managed Piantala catalog when it is unused."""
    icon = ManagedMdiIcon.query.get_or_404(icon_id)
    form = DeleteForm()
    if form.validate_on_submit():
        usage_rows = _mdi_icon_usage_rows(icon.icon_name_normalized)
        if usage_rows:
            flash("This icon is still used in Piantala. Open its usage list before removing it.", "warning")
        else:
            db.session.delete(icon)
            db.session.commit()
            flash("Icon removed from the Piantala catalog.", "success")
    return redirect(url_for("admin.mdi_icons"))


@bp.route("/storage")
@login_required
@permission_required("manage_users")
def storage():
    """Show database and upload directory usage for administrators."""
    db_path = _sqlite_database_path()
    db_size_bytes = None
    if db_path is not None and db_path.exists():
        db_size_bytes = db_path.stat().st_size

    upload_dir = _upload_directory()
    upload_size_bytes = _upload_directory_size(upload_dir)
    upload_file_count = len([path for path in upload_dir.rglob("*") if path.is_file()]) if upload_dir.exists() else 0

    return render_template(
        "admin_storage.html",
        settings=GardenSettings.get_or_create(),
        image_tools_available=Image is not None,
        db_path=str(db_path) if db_path is not None else None,
        db_size_bytes=db_size_bytes,
        db_size_label=_format_bytes(db_size_bytes),
        upload_dir=str(upload_dir),
        upload_size_bytes=upload_size_bytes,
        upload_size_label=_format_bytes(upload_size_bytes),
        upload_file_count=upload_file_count,
        image_dir=str(upload_dir),
    )


@bp.route("/environment")
@login_required
@permission_required("manage_users")
def environment():
    """Show runtime, package, and filesystem diagnostics for the current server."""
    install_root = Path(current_app.root_path).resolve().parent
    disk_usage = shutil.disk_usage(install_root)
    request_server_software = request.environ.get("SERVER_SOFTWARE") or "unknown"
    known_packages = [
        "piantala",
        "Flask",
        "Flask-Login",
        "Flask-SQLAlchemy",
        "Flask-WTF",
        "SQLAlchemy",
        "Pillow",
        "gunicorn",
        "Werkzeug",
        "python-dotenv",
    ]
    package_rows = [
        {
            "name": package_name,
            "version": _runtime_package_version(package_name),
        }
        for package_name in known_packages
    ]
    installed_packages = sorted(
        [
            {
                "name": distribution.metadata.get("Name") or str(distribution),
                "version": distribution.version,
            }
            for distribution in distributions()
        ],
        key=lambda item: item["name"].lower(),
    )

    return render_template(
        "admin_environment.html",
        settings=GardenSettings.get_or_create(),
        install_root=str(install_root),
        is_docker=Path("/.dockerenv").exists(),
        python_version=sys.version.split()[0],
        python_executable=sys.executable,
        pip_version=_runtime_package_version("pip"),
        platform_label=platform.platform(),
        server_software=request_server_software,
        package_rows=package_rows,
        installed_packages=installed_packages,
        disk_total_label=_format_bytes(disk_usage.total),
        disk_used_label=_format_bytes(disk_usage.used),
        disk_free_label=_format_bytes(disk_usage.free),
        disk_total_bytes=disk_usage.total,
        disk_used_bytes=disk_usage.used,
        disk_free_bytes=disk_usage.free,
    )


@bp.route("/access", methods=["GET", "POST"])
@login_required
def access_settings():
    """Configure self-registration and email delivery for the whole platform."""
    if not current_user.has_global_permission("manage_users"):
        flash("Only platform administrators can change access settings.", "danger")
        return redirect(url_for("admin.index"))

    settings = PlatformSettings.get_or_create()
    form = PlatformSettingsForm(obj=settings)
    if form.validate_on_submit():
        settings.allow_self_registration = form.allow_self_registration.data
        settings.public_base_url = form.public_base_url.data
        settings.mail_from_name = form.mail_from_name.data
        settings.mail_from_email = form.mail_from_email.data
        settings.smtp_preset = form.smtp_preset.data
        settings.smtp_host = form.smtp_host.data
        settings.smtp_port = form.smtp_port.data or 587
        settings.smtp_username = form.smtp_username.data
        if settings.smtp_preset == "docker_mailpit":
            settings.smtp_username = None
            settings.smtp_password = None
        elif form.smtp_password.data:
            settings.smtp_password = form.smtp_password.data
        settings.smtp_use_tls = form.smtp_use_tls.data
        settings.smtp_use_ssl = form.smtp_use_ssl.data
        db.session.commit()
        flash("Access settings updated.", "success")
        return redirect(url_for("admin.access_settings"))

    return render_template(
        "access_settings.html",
        form=form,
        settings=GardenSettings.get_or_create(),
        smtp_provider_defaults=SMTP_PROVIDER_DEFAULTS,
    )


@bp.route("/storage/uploads")
@login_required
@permission_required("manage_users")
def upload_inventory():
    """List uploaded images with size and usage references."""
    selected_folder = (request.args.get("folder") or "").strip() or None
    unused_only = request.args.get("show") == "unused"
    requested_view = (request.args.get("view") or "").strip().lower()
    view_mode = requested_view if requested_view in {"list", "thumbs"} else "list"
    back_target = None
    if unused_only and selected_folder:
        back_target = url_for("admin.upload_inventory", folder=selected_folder, view=view_mode)
    elif unused_only or selected_folder:
        back_target = url_for("admin.upload_inventory")
    folder_inventory = _upload_folder_inventory()
    inventory = _upload_inventory(selected_folder, unused_only=unused_only)
    total_size = sum(item["size_bytes"] or 0 for item in inventory)
    return render_template(
        "admin_upload_inventory.html",
        settings=GardenSettings.get_or_create(),
        image_tools_available=Image is not None,
        folder_inventory=folder_inventory,
        selected_folder=selected_folder,
        unused_only=unused_only,
        view_mode=view_mode,
        back_target=back_target,
        inventory=inventory,
        total_size_label=_format_bytes(total_size),
        total_files=len(inventory),
        delete_form=DeleteForm(),
        cleanup_form=ActionForm(prefix="cleanup"),
    )


@bp.route("/storage/uploads/delete-orphan", methods=["POST"])
@login_required
@permission_required("manage_users")
def delete_orphan_upload():
    """Delete one upload file only when it is not referenced anywhere."""
    form = DeleteForm()
    relative_path = request.form.get("relative_path", "").strip()
    if form.validate_on_submit() and relative_path:
        if _delete_upload_file(relative_path):
            flash("Unused upload file deleted.", "success")
        else:
            flash("That file is still referenced or could not be deleted.", "warning")
    return redirect(url_for("admin.upload_inventory"))


@bp.route("/storage/uploads/delete-unused", methods=["POST"])
@login_required
@permission_required("manage_users")
def delete_unused_uploads():
    """Delete every upload file that is currently orphaned."""
    form = ActionForm(prefix="cleanup")
    if form.validate_on_submit():
        removed_count = 0
        for item in _upload_inventory():
            if item["usages"] or item["missing"]:
                continue
            if _delete_upload_file(str(item["relative_path"])):
                removed_count += 1
        flash(f"Deleted {removed_count} unused upload file(s).", "success")
    return redirect(url_for("admin.upload_inventory"))


def _last_active_admin_guard(user: User, selected_roles: list[Role], is_active: bool) -> bool:
    """Prevent removing or disabling the last active admin account.

    Parameters:
        user: User being edited.
        selected_roles: Roles that will remain assigned after saving.
        is_active: Whether the edited user should stay active.
    """
    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role is None:
        return False

    user_is_admin = admin_role in user.roles
    selected_is_admin = any(role.id == admin_role.id for role in selected_roles)
    if not user_is_admin:
        return False

    active_admins = [
        candidate
        for candidate in User.query.all()
        if candidate.is_active and any(role.id == admin_role.id for role in candidate.roles)
    ]
    if len(active_admins) != 1 or active_admins[0].id != user.id:
        return False

    return (not is_active) or (not selected_is_admin)


@bp.route("/users")
@login_required
@permission_required("manage_users")
def users():
    """Render current-site membership management and invitations."""
    site = require_current_site()
    invite_form = SiteInviteForm(prefix="invite")
    roles = Role.query.order_by(Role.name).all()
    invite_form.role_id.choices = [(role.id, role.name) for role in roles]
    memberships = (
        SiteMembership.query.filter_by(site_id=site.id)
        .join(User, SiteMembership.user_id == User.id)
        .order_by(User.username)
        .all()
    )
    pending_invites = (
        AuthToken.query.filter_by(purpose="site_invite", site_id=site.id, used_at=None)
        .order_by(db.desc(AuthToken.created_at))
        .all()
    )
    return render_template(
        "users.html",
        memberships=memberships,
        pending_invites=pending_invites,
        invite_form=invite_form,
        delete_form=DeleteForm(),
        site=site,
        settings=GardenSettings.get_or_create(),
        ha_settings=HomeAssistantSettings.get_or_create(),
    )


@bp.route("/users/invite", methods=["POST"])
@login_required
@permission_required("manage_users")
def invite_site_user():
    """Send one site invitation email for the current site."""
    site = require_current_site()
    form = SiteInviteForm(prefix="invite")
    roles = Role.query.order_by(Role.name).all()
    form.role_id.choices = [(role.id, role.name) for role in roles]
    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "danger")
        return redirect(url_for("admin.users"))

    role = next((candidate for candidate in roles if candidate.id == form.role_id.data), None)
    if role is None:
        flash("Selected role was not found.", "danger")
        return redirect(url_for("admin.users"))

    platform_settings = PlatformSettings.get_or_create()
    if not platform_settings.smtp_is_configured:
        flash("SMTP is not configured yet. Complete platform access settings before sending invitations.", "danger")
        return redirect(url_for("admin.users"))

    invited_email = form.email.data
    existing_user = User.query.filter_by(email=invited_email).first()
    if existing_user is not None:
        existing_membership = SiteMembership.query.filter_by(site_id=site.id, user_id=existing_user.id).first()
        if existing_membership is not None:
            flash("That user already belongs to this site.", "warning")
            return redirect(url_for("admin.users"))

    token, raw_token = AuthToken.issue(
        purpose="site_invite",
        expires_in_hours=72,
        email=invited_email,
        site=site,
        role=role,
        payload={"invited_by": current_user.username},
    )
    db.session.flush()
    try:
        send_email(
            to_email=invited_email,
            subject=f"Invitation to join {site.name} on Piantala",
            text_body=(
                f"You have been invited to join the site '{site.name}' on Piantala as {role.name}.\n\n"
                f"Open this link to accept the invitation:\n\n"
                f"{_build_external_url('auth.accept_invite', token=raw_token)}\n\n"
                "If you do not want to join this site, you can ignore this email."
            ),
        )
    except MailError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("admin.users"))

    db.session.commit()
    flash("Invitation sent.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/invitations/<int:token_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_users")
def delete_site_invitation(token_id: int):
    """Cancel one pending invitation for the current site."""
    site = require_current_site()
    token = AuthToken.query.filter_by(id=token_id, purpose="site_invite", site_id=site.id).first_or_404()
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(token)
        db.session.commit()
        flash("Invitation removed.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def create_user():
    """Create a new Piantala user from the admin panel."""
    form = UserForm()
    roles = Role.query.order_by(Role.name).all()
    form.roles.choices = [(role.id, role.name) for role in roles]

    if form.validate_on_submit():
        email_value = form.email.data or None
        user = User(
            username=form.username.data,
            email=email_value,
            preferred_locale=form.preferred_locale.data,
            is_active=form.is_active.data,
        )
        user.set_password(form.password.data)
        user.roles = [role for role in roles if role.id in form.roles.data]
        db.session.add(user)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "user_form.html",
        form=form,
        user=None,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def edit_user(user_id: int):
    """Edit an existing user account.

    Parameters:
        user_id: Identifier of the user being edited.
    """
    user = User.query.get_or_404(user_id)
    roles = Role.query.order_by(Role.name).all()
    form = UserForm(user=user, obj=user)
    form.roles.choices = [(role.id, role.name) for role in roles]

    if not form.is_submitted():
        form.roles.data = [role.id for role in user.roles]

    if form.validate_on_submit():
        selected_roles = [role for role in roles if role.id in form.roles.data]
        if _last_active_admin_guard(user, selected_roles, form.is_active.data):
            flash("Piantala must keep at least one active admin user.", "danger")
            return render_template(
                "user_form.html",
                form=form,
                user=user,
                settings=GardenSettings.get_or_create(),
            )

        user.username = form.username.data.strip()
        user.email = form.email.data or None
        user.preferred_locale = form.preferred_locale.data
        user.is_active = form.is_active.data
        user.roles = selected_roles
        if form.password.data:
            user.set_password(form.password.data)

        db.session.commit()
        if current_user.id == user.id and not user.is_active:
            flash("Your account was disabled. Contact another administrator.", "warning")
        else:
            flash("User updated.", "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "user_form.html",
        form=form,
        user=user,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/home-assistant", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def home_assistant_settings():
    """Display and save Home Assistant integration settings."""
    ha_settings = HomeAssistantSettings.get_or_create()
    form = HomeAssistantSettingsForm(obj=ha_settings)
    if not form.is_submitted():
        form.access_token.data = ""
        form.internal_url.data = ha_settings.internal_url
        form.user_agent.data = ha_settings.user_agent
    test_form = ActionForm(prefix="test")
    sync_form = ActionForm(prefix="sync")

    if form.validate_on_submit():
        ha_settings.base_url = form.base_url.data.strip() if form.base_url.data else None
        ha_settings.internal_url = (
            form.internal_url.data.strip()
            if form.internal_url.data
            else None
        )
        if form.access_token.data:
            ha_settings.access_token = form.access_token.data.strip()
        ha_settings.user_agent = (
            form.user_agent.data.strip()
            if form.user_agent.data
            else ha_settings.user_agent
        )
        ha_settings.verify_ssl = form.verify_ssl.data
        ha_settings.request_timeout = form.request_timeout.data or 10
        db.session.commit()
        flash("Home Assistant settings saved.", "success")
        return redirect(url_for("admin.home_assistant_settings"))
    elif form.is_submitted():
        flash("Home Assistant settings were not saved. Check the validation errors below.", "danger")

    return render_template(
        "home_assistant_settings.html",
        form=form,
        test_form=test_form,
        sync_form=sync_form,
        ha_settings=ha_settings,
        entity_count=HomeAssistantEntityCatalog.query.count(),
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/home-assistant/test", methods=["POST"])
@login_required
@permission_required("manage_users")
def home_assistant_test():
    """Test the saved Home Assistant connection settings."""
    ha_settings = HomeAssistantSettings.get_or_create()
    form = ActionForm(prefix="test")
    if form.validate_on_submit():
        try:
            message = test_connection(ha_settings)
            ha_settings.last_error = None
            db.session.commit()
            flash(f"Home Assistant connection succeeded: {message}", "success")
        except HomeAssistantError as exc:
            ha_settings.last_error = str(exc)
            db.session.commit()
            flash(str(exc), "danger")
    return redirect(url_for("admin.home_assistant_settings"))


@bp.route("/home-assistant/sync", methods=["POST"])
@login_required
@permission_required("manage_users")
def home_assistant_sync():
    """Synchronize the local Home Assistant entity catalog."""
    ha_settings = HomeAssistantSettings.get_or_create()
    form = ActionForm(prefix="sync")
    if form.validate_on_submit():
        try:
            count = sync_entity_catalog(ha_settings)
            flash(f"Synced {count} Home Assistant entities.", "success")
        except HomeAssistantError as exc:
            ha_settings.last_error = str(exc)
            db.session.commit()
            flash(str(exc), "danger")
    return redirect(url_for("admin.home_assistant_settings"))


@bp.route("/translations", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def translations():
    """Edit translation overrides stored in the database."""
    form = ActionForm(prefix="translations")
    entries = TranslationEntry.query.order_by(TranslationEntry.key, TranslationEntry.locale).all()

    if form.validate_on_submit():
        for entry in entries:
            field_name = f"translation-{entry.id}"
            submitted_value = request.form.get(field_name)
            if submitted_value is not None:
                entry.text = submitted_value.strip() or entry.text
        db.session.commit()
        flash("Translations updated.", "success")
        return redirect(url_for("admin.translations"))

    translations_by_key: dict[str, dict[str, TranslationEntry]] = {}
    for entry in entries:
        translations_by_key.setdefault(entry.key, {})[entry.locale] = entry

    return render_template(
        "translations.html",
        form=form,
        translations_by_key=translations_by_key,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/activity-types", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def activity_types():
    """Create and list activity types used in node history."""
    form = ActivityTypeForm()

    if form.validate_on_submit():
        existing = ActivityType.query.filter_by(name=form.name.data.strip()).first()
        if existing is not None:
            flash("An activity type with that name already exists.", "warning")
        else:
            db.session.add(
                ActivityType(
                    name=form.name.data.strip(),
                    description=form.description.data.strip() if form.description.data else None,
                    tracks_quantity_kg=form.tracks_quantity_kg.data,
                    sort_order=form.sort_order.data or 0,
                )
            )
            db.session.commit()
            flash("Activity type created.", "success")
            return redirect(url_for("admin.activity_types"))

    return render_template(
        "activity_types.html",
        form=form,
        delete_form=DeleteForm(),
        activity_types=ActivityType.query.order_by(ActivityType.sort_order, ActivityType.name).all(),
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/activity-types/<int:activity_type_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_activity_type(activity_type_id: int):
    """Edit an existing activity type.

    Parameters:
        activity_type_id: Identifier of the activity type being edited.
    """
    activity_type = ActivityType.query.get_or_404(activity_type_id)
    form = ActivityTypeForm(obj=activity_type)

    if form.validate_on_submit():
        existing = ActivityType.query.filter(
            ActivityType.name == form.name.data.strip(),
            ActivityType.id != activity_type.id,
        ).first()
        if existing is not None:
            flash("An activity type with that name already exists.", "warning")
        else:
            activity_type.name = form.name.data.strip()
            activity_type.description = form.description.data.strip() if form.description.data else None
            activity_type.tracks_quantity_kg = form.tracks_quantity_kg.data
            activity_type.sort_order = form.sort_order.data or 0
            db.session.commit()
            flash("Activity type updated.", "success")
            return redirect(url_for("admin.activity_types"))

    return render_template(
        "activity_type_form.html",
        form=form,
        activity_type=activity_type,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/activity-types/<int:activity_type_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_activity_type(activity_type_id: int):
    """Delete an activity type when it is no longer referenced.

    Parameters:
        activity_type_id: Identifier of the activity type to remove.
    """
    activity_type = ActivityType.query.get_or_404(activity_type_id)
    form = DeleteForm()
    if form.validate_on_submit():
        if NodeActivity.query.filter_by(activity_type_id=activity_type.id).first() is not None:
            flash("This activity type is already used in history records and cannot be deleted.", "warning")
        else:
            db.session.delete(activity_type)
            db.session.commit()
            flash("Activity type deleted.", "success")
    return redirect(url_for("admin.activity_types"))


@bp.route("/marker-colors", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def marker_colors():
    """Create and list marker colors available for node hotspots."""
    form = MarkerColorForm()

    if form.validate_on_submit():
        if MarkerColor.query.count() >= 16:
            flash("Piantala supports up to 16 marker colors.", "warning")
        else:
            existing = MarkerColor.query.filter_by(name=form.name.data.strip()).first()
            if existing is not None:
                flash("A marker color with that name already exists.", "warning")
            else:
                db.session.add(
                    MarkerColor(
                        name=form.name.data.strip(),
                        hex_value=form.hex_value.data.strip(),
                        sort_order=form.sort_order.data or 0,
                    )
                )
                db.session.commit()
                flash("Marker color created.", "success")
                return redirect(url_for("admin.marker_colors"))

    return render_template(
        "marker_colors.html",
        form=form,
        delete_form=DeleteForm(),
        marker_colors=MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all(),
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/marker-colors/<int:marker_color_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_marker_color(marker_color_id: int):
    """Edit one marker color and propagate its hex value to linked nodes.

    Parameters:
        marker_color_id: Identifier of the marker color being edited.
    """
    marker_color = MarkerColor.query.get_or_404(marker_color_id)
    form = MarkerColorForm(obj=marker_color)

    if form.validate_on_submit():
        existing = MarkerColor.query.filter(
            MarkerColor.name == form.name.data.strip(),
            MarkerColor.id != marker_color.id,
        ).first()
        if existing is not None:
            flash("A marker color with that name already exists.", "warning")
        else:
            marker_color.name = form.name.data.strip()
            marker_color.hex_value = form.hex_value.data.strip()
            marker_color.sort_order = form.sort_order.data or 0
            for node in marker_color.nodes:
                node.hotspot_color = marker_color.hex_value
            db.session.commit()
            flash("Marker color updated.", "success")
            return redirect(url_for("admin.marker_colors"))

    return render_template(
        "marker_color_form.html",
        form=form,
        marker_color=marker_color,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/marker-colors/<int:marker_color_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_marker_color(marker_color_id: int):
    """Delete a marker color when no nodes still use it.

    Parameters:
        marker_color_id: Identifier of the marker color to remove.
    """
    marker_color = MarkerColor.query.get_or_404(marker_color_id)
    form = DeleteForm()
    if form.validate_on_submit():
        if GardenNode.query.filter_by(marker_color_id=marker_color.id).first() is not None:
            flash("This marker color is already used by nodes and cannot be deleted.", "warning")
        else:
            db.session.delete(marker_color)
            db.session.commit()
            flash("Marker color deleted.", "success")
    return redirect(url_for("admin.marker_colors"))


@bp.route("/link-types", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def link_types():
    """Create and list link types used for external references."""
    form = LinkTypeForm()
    link_type_names = _link_type_name_values()
    link_type_name_errors: dict[str, str] = {}

    if form.is_submitted():
        link_type_name_errors = _link_type_name_errors(link_type_names)
        if form.validate() and not link_type_name_errors:
            canonical_name = link_type_names[DEFAULT_LOCALE]
            existing = LinkType.query.filter_by(name=canonical_name).first()
            if existing is not None:
                flash("A link type with that English name already exists.", "warning")
            else:
                link_type = LinkType(
                    name=canonical_name,
                    description=form.description.data.strip() if form.description.data else None,
                    sort_order=form.sort_order.data or 0,
                    requires_label=form.requires_label.data,
                    requires_url=form.requires_url.data,
                )
                db.session.add(link_type)
                db.session.flush()
                link_type.save_localized_names(link_type_names)
                db.session.commit()
                flash("Link type created.", "success")
                return redirect(url_for("admin.link_types"))

    return render_template(
        "link_types.html",
        form=form,
        delete_form=DeleteForm(),
        link_types=LinkType.query.order_by(LinkType.sort_order, LinkType.name).all(),
        link_type_names=link_type_names,
        link_type_name_errors=link_type_name_errors,
        supported_locales=SUPPORTED_LOCALES,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/link-types/<int:link_type_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_link_type(link_type_id: int):
    """Edit an existing link type and its localized names.

    Parameters:
        link_type_id: Identifier of the link type being edited.
    """
    link_type = LinkType.query.get_or_404(link_type_id)
    form = LinkTypeForm(obj=link_type)
    link_type_names = _link_type_name_values(link_type)
    link_type_name_errors: dict[str, str] = {}

    if form.is_submitted():
        link_type_name_errors = _link_type_name_errors(link_type_names)
        if form.validate() and not link_type_name_errors:
            canonical_name = link_type_names[DEFAULT_LOCALE]
            existing = LinkType.query.filter(
                LinkType.name == canonical_name,
                LinkType.id != link_type.id,
            ).first()
            if existing is not None:
                flash("A link type with that English name already exists.", "warning")
            else:
                link_type.name = canonical_name
                link_type.description = form.description.data.strip() if form.description.data else None
                link_type.sort_order = form.sort_order.data or 0
                link_type.requires_label = form.requires_label.data
                link_type.requires_url = form.requires_url.data
                db.session.flush()
                link_type.save_localized_names(link_type_names)
                db.session.commit()
                flash("Link type updated.", "success")
                return redirect(url_for("admin.link_types"))

    return render_template(
        "link_type_form.html",
        form=form,
        link_type=link_type,
        link_type_names=link_type_names,
        link_type_name_errors=link_type_name_errors,
        supported_locales=SUPPORTED_LOCALES,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/link-types/<int:link_type_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_link_type(link_type_id: int):
    """Delete a link type when no node links still reference it.

    Parameters:
        link_type_id: Identifier of the link type to remove.
    """
    link_type = LinkType.query.get_or_404(link_type_id)
    form = DeleteForm()
    if form.validate_on_submit():
        if NodeExternalLink.query.filter_by(link_type_id=link_type.id).first() is not None:
            flash("This link type is already used and cannot be deleted.", "warning")
        else:
            db.session.delete(link_type)
            db.session.commit()
            flash("Link type deleted.", "success")
    return redirect(url_for("admin.link_types"))


@bp.route("/cultivation-types", methods=["GET"])
@login_required
@permission_required("manage_content")
def cultivation_types():
    """Create and list cultivation types used when loading cultivations."""
    return render_template(
        "cultivation_types.html",
        delete_form=DeleteForm(),
        cultivation_types=CultivationType.query.order_by(
            CultivationType.botanical_name,
            CultivationType.common_name,
            CultivationType.id,
        ).all(),
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-types/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def create_cultivation_type():
    """Create one cultivation type in a dedicated form page."""
    form = CultivationTypeForm()
    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
    form.default_marker_color_id.choices = [(0, "Use node default")] + [
        (marker_color.id, f"{marker_color.name} ({marker_color.hex_value})")
        for marker_color in marker_colors
    ]
    form.default_marker_icon.choices = _marker_icon_choices()

    if form.validate_on_submit():
        signature = _cultivation_type_signature(
            form.botanical_name.data,
            form.common_name.data,
            form.life_cycle.data,
        )
        duplicate = next(
            (
                cultivation_type
                for cultivation_type in CultivationType.query.order_by(CultivationType.id).all()
                if _cultivation_type_signature(
                    cultivation_type.botanical_name,
                    cultivation_type.common_name,
                    cultivation_type.life_cycle,
                ) == signature
            ),
            None,
        )
        if duplicate is not None:
            if not duplicate.external_url:
                duplicate.external_url = _normalized_optional_text(form.external_url.data)
            db.session.commit()
            flash("That cultivation type already exists.", "warning")
            return redirect(url_for("admin.edit_cultivation_type", cultivation_type_id=duplicate.id))
        else:
            db.session.add(
                CultivationType(
                    botanical_name=_normalized_optional_text(form.botanical_name.data),
                    common_name=_normalized_optional_text(form.common_name.data),
                    life_cycle=_normalized_optional_text(form.life_cycle.data),
                    external_url=_normalized_optional_text(form.external_url.data),
                    default_marker_color_id=form.default_marker_color_id.data or None,
                    default_marker_icon=_normalized_marker_icon(form.default_marker_icon.data),
                )
            )
            db.session.commit()
            flash("Cultivation type created.", "success")
            return redirect(url_for("admin.cultivation_types"))

    return render_template(
        "cultivation_type_form.html",
        form=form,
        cultivation_type=None,
        delete_form=DeleteForm(),
        action_form=ActionForm(),
        marker_colors=marker_colors,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-types/<int:cultivation_type_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_cultivation_type(cultivation_type_id: int):
    """Edit one cultivation type and manage its reference images.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type being edited.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    form = CultivationTypeForm(obj=cultivation_type)
    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
    form.default_marker_color_id.choices = [(0, "Use node default")] + [
        (marker_color.id, f"{marker_color.name} ({marker_color.hex_value})")
        for marker_color in marker_colors
    ]
    form.default_marker_icon.choices = _marker_icon_choices(cultivation_type.default_marker_icon)
    if request.method == "GET":
        form.default_marker_color_id.data = cultivation_type.default_marker_color_id or 0

    if form.validate_on_submit():
        signature = _cultivation_type_signature(
            form.botanical_name.data,
            form.common_name.data,
            form.life_cycle.data,
        )
        duplicate = next(
            (
                candidate
                for candidate in CultivationType.query.order_by(CultivationType.id).all()
                if candidate.id != cultivation_type.id
                and _cultivation_type_signature(
                    candidate.botanical_name,
                    candidate.common_name,
                    candidate.life_cycle,
                ) == signature
            ),
            None,
        )
        if duplicate is not None:
            flash("A cultivation type with the same names and lifecycle already exists.", "warning")
        else:
            cultivation_type.botanical_name = _normalized_optional_text(form.botanical_name.data)
            cultivation_type.common_name = _normalized_optional_text(form.common_name.data)
            cultivation_type.life_cycle = _normalized_optional_text(form.life_cycle.data)
            cultivation_type.external_url = _normalized_optional_text(form.external_url.data)
            cultivation_type.default_marker_color_id = form.default_marker_color_id.data or None
            cultivation_type.default_marker_icon = _normalized_marker_icon(form.default_marker_icon.data)
            db.session.commit()
            flash("Cultivation type updated.", "success")
            return redirect(url_for("admin.cultivation_types"))

    return render_template(
        "cultivation_type_form.html",
        form=form,
        cultivation_type=cultivation_type,
        delete_form=DeleteForm(),
        action_form=ActionForm(),
        marker_colors=marker_colors,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-types/<int:cultivation_type_id>/usage", methods=["GET"])
@login_required
@permission_required("manage_content")
def cultivation_type_usage(cultivation_type_id: int):
    """Show which cultivations currently use one cultivation type.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type being inspected.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    return render_template(
        "cultivation_type_usage.html",
        cultivation_type=cultivation_type,
        cultivation_nodes=cultivation_type.site_usage_nodes,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-types/<int:cultivation_type_id>/apply-marker-defaults", methods=["POST"])
@login_required
@permission_required("manage_content")
def apply_cultivation_type_marker_defaults(cultivation_type_id: int):
    """Rewrite marker color/icon on cultivations linked to one cultivation type.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type whose nodes should be updated.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    form = ActionForm()
    if form.validate_on_submit():
        updated_count = _apply_cultivation_type_marker_defaults(cultivation_type)
        db.session.commit()
        flash(f"Updated {updated_count} cultivation(s) from cultivation-type marker defaults.", "success")
    return redirect(url_for("admin.edit_cultivation_type", cultivation_type_id=cultivation_type.id))


@bp.route("/cultivation-types/<int:cultivation_type_id>/variants", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def cultivation_type_variants(cultivation_type_id: int):
    """Create and list variants for one cultivation type.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type whose variants are managed.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    form = CultivationTypeVariantForm()
    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
    form.default_marker_color_id.choices = [(0, "Use cultivation type default")] + [
        (marker_color.id, f"{marker_color.name} ({marker_color.hex_value})")
        for marker_color in marker_colors
    ]

    if form.validate_on_submit():
        variant_name = (form.name.data or "").strip()
        duplicate = next(
            (
                variant
                for variant in cultivation_type.variants
                if variant.name.casefold() == variant_name.casefold()
            ),
            None,
        )
        if duplicate is not None:
            flash("A variant with that name already exists for this cultivation type.", "warning")
        else:
            db.session.add(
                CultivationTypeVariant(
                    cultivation_type=cultivation_type,
                    name=variant_name,
                    sort_order=form.sort_order.data or 0,
                    default_marker_color_id=form.default_marker_color_id.data or None,
                )
            )
            db.session.commit()
            flash("Variant created.", "success")
            return redirect(url_for("admin.cultivation_type_variants", cultivation_type_id=cultivation_type.id))

    return render_template(
        "cultivation_type_variants.html",
        cultivation_type=cultivation_type,
        form=form,
        delete_form=DeleteForm(),
        marker_colors=marker_colors,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-type-variants/<int:variant_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_cultivation_type_variant(variant_id: int):
    """Edit one cultivation variant.

    Parameters:
        variant_id: Identifier of the cultivation variant being edited.
    """
    variant = CultivationTypeVariant.query.get_or_404(variant_id)
    cultivation_type = variant.cultivation_type
    form = CultivationTypeVariantForm(obj=variant)
    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
    form.default_marker_color_id.choices = [(0, "Use cultivation type default")] + [
        (marker_color.id, f"{marker_color.name} ({marker_color.hex_value})")
        for marker_color in marker_colors
    ]
    if request.method == "GET":
        form.default_marker_color_id.data = variant.default_marker_color_id or 0

    if form.validate_on_submit():
        variant_name = (form.name.data or "").strip()
        duplicate = next(
            (
                candidate
                for candidate in cultivation_type.variants
                if candidate.id != variant.id and candidate.name.casefold() == variant_name.casefold()
            ),
            None,
        )
        if duplicate is not None:
            flash("A variant with that name already exists for this cultivation type.", "warning")
        else:
            variant.name = variant_name
            variant.sort_order = form.sort_order.data or 0
            variant.default_marker_color_id = form.default_marker_color_id.data or None
            db.session.commit()
            flash("Variant updated.", "success")
            return redirect(url_for("admin.cultivation_type_variants", cultivation_type_id=cultivation_type.id))

    return render_template(
        "cultivation_type_variant_form.html",
        cultivation_type=cultivation_type,
        variant=variant,
        form=form,
        marker_colors=marker_colors,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-type-variants/<int:variant_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_cultivation_type_variant(variant_id: int):
    """Delete one cultivation variant when it is no longer used by nodes.

    Parameters:
        variant_id: Identifier of the cultivation variant to remove.
    """
    variant = CultivationTypeVariant.query.get_or_404(variant_id)
    cultivation_type_id = variant.cultivation_type_id
    form = DeleteForm()
    if form.validate_on_submit():
        if GardenNode.query.filter_by(cultivation_type_variant_id=variant.id).first() is not None:
            flash("This variant is already used by cultivations and cannot be deleted.", "warning")
        else:
            db.session.delete(variant)
            db.session.commit()
            flash("Variant deleted.", "success")
    return redirect(url_for("admin.cultivation_type_variants", cultivation_type_id=cultivation_type_id))


@bp.route("/cultivation-types/<int:cultivation_type_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_cultivation_type(cultivation_type_id: int):
    """Delete a cultivation type when it is no longer used by nodes.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type to remove.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    form = DeleteForm()
    if form.validate_on_submit():
        if GardenNode.query.filter_by(cultivation_type_id=cultivation_type.id).first() is not None:
            flash("This cultivation type is already used by cultivations and cannot be deleted.", "warning")
        else:
            db.session.delete(cultivation_type)
            db.session.commit()
            flash("Cultivation type deleted.", "success")
    return redirect(url_for("admin.cultivation_types"))


@bp.route("/cultivation-types/<int:cultivation_type_id>/images/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def add_cultivation_type_image(cultivation_type_id: int):
    """Upload one image linked to a cultivation type.

    Parameters:
        cultivation_type_id: Identifier of the cultivation type receiving the image.
    """
    cultivation_type = CultivationType.query.get_or_404(cultivation_type_id)
    form = CultivationTypeImageForm()

    if form.validate_on_submit():
        if form.image.data is None or not form.image.data.filename:
            form.image.errors.append("Choose an image to upload.")
        else:
            image_path = save_uploaded_file(
                form.image.data,
                "cultivation-type",
                image_kind="node_photo",
                subfolder=f"cultivation-types/{cultivation_type.id}",
            )
            image_title = (form.title.data or "").strip() or Path(form.image.data.filename).stem
            db.session.add(
                CultivationTypeImage(
                    cultivation_type=cultivation_type,
                    title=image_title,
                    caption=_normalized_optional_text(form.caption.data),
                    image_path=image_path,
                    sort_order=form.sort_order.data or 0,
                )
            )
            db.session.commit()
            flash("Cultivation type image added.", "success")
            return redirect(url_for("admin.edit_cultivation_type", cultivation_type_id=cultivation_type.id))

    return render_template(
        "cultivation_type_image_form.html",
        form=form,
        cultivation_type=cultivation_type,
        image_record=None,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-type-images/<int:image_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_cultivation_type_image(image_id: int):
    """Edit one cultivation type image and optionally replace the file.

    Parameters:
        image_id: Identifier of the cultivation type image being edited.
    """
    image_record = CultivationTypeImage.query.get_or_404(image_id)
    cultivation_type = image_record.cultivation_type
    form = CultivationTypeImageForm(obj=image_record)

    if form.validate_on_submit():
        image_record.title = (form.title.data or "").strip() or image_record.title
        image_record.caption = _normalized_optional_text(form.caption.data)
        image_record.sort_order = form.sort_order.data or 0
        if form.image.data is not None and form.image.data.filename:
            image_record.image_path = save_uploaded_file(
                form.image.data,
                "cultivation-type",
                image_kind="node_photo",
                subfolder=f"cultivation-types/{cultivation_type.id}",
            )
        db.session.commit()
        flash("Cultivation type image updated.", "success")
        return redirect(url_for("admin.edit_cultivation_type", cultivation_type_id=cultivation_type.id))

    return render_template(
        "cultivation_type_image_form.html",
        form=form,
        cultivation_type=cultivation_type,
        image_record=image_record,
        settings=GardenSettings.get_or_create(),
    )


@bp.route("/cultivation-type-images/<int:image_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_cultivation_type_image(image_id: int):
    """Delete one cultivation type image.

    Parameters:
        image_id: Identifier of the cultivation type image to remove.
    """
    image_record = CultivationTypeImage.query.get_or_404(image_id)
    cultivation_type_id = image_record.cultivation_type_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(image_record)
        db.session.commit()
        flash("Cultivation type image deleted.", "success")
    return redirect(url_for("admin.edit_cultivation_type", cultivation_type_id=cultivation_type_id))
