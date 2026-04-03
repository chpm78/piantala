from __future__ import annotations

import base64
import binascii
from functools import wraps
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from flask import abort, current_app, flash
from flask_login import current_user
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .media import max_dimension_for_kind, optimize_image_file
from .site_context import current_site


LEVEL_TYPE_DEFAULTS = {
    1: "area",
    2: "section",
    3: "bed",
    4: "plant",
}


class StorageLimitError(Exception):
    """Raised when one upload would exceed the configured storage quotas."""


def _format_bytes(size_in_bytes: int | None) -> str:
    """Return one human-readable byte label."""
    if size_in_bytes is None:
        return "—"
    size = float(size_in_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_in_bytes} B"


def _upload_directory() -> Path:
    """Return the absolute upload directory configured for Piantala."""
    return Path(current_app.config["UPLOAD_FOLDER"])


def _sqlite_database_path() -> Path | None:
    """Return the SQLite database path when Piantala currently uses SQLite."""
    database_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    prefix = "sqlite:///"
    if not database_uri.startswith(prefix):
        return None
    return Path(database_uri.removeprefix(prefix))


def _mb_to_bytes(limit_mb: int | None) -> int | None:
    """Convert one megabyte quota value to bytes."""
    if limit_mb is None:
        return None
    return max(int(limit_mb), 0) * 1024 * 1024


def upload_directory_size_bytes() -> int:
    """Return the total size of the configured upload directory."""
    upload_dir = _upload_directory()
    if not upload_dir.exists():
        return 0
    return sum(path.stat().st_size for path in upload_dir.rglob("*") if path.is_file())


def total_webapp_storage_usage_bytes() -> int:
    """Return current total storage used by the webapp database and uploads."""
    total = upload_directory_size_bytes()
    db_path = _sqlite_database_path()
    if db_path is not None and db_path.exists():
        total += db_path.stat().st_size
    return total


def site_storage_usage_bytes(site=None) -> int:
    """Return upload bytes referenced by one site.

    Parameters:
        site: Site whose upload usage should be measured. When omitted,
            the current request site is used if available.
    """
    from .media import relative_upload_to_fs_path
    from .models import GardenNode, GardenSettings, NodeActivity, NodeActivityImage, NodePhoto

    site = site or current_site()
    if site is None:
        return 0

    upload_dir = _upload_directory()
    referenced_paths: set[str] = set()

    settings = GardenSettings.query.filter_by(site_id=site.id).first()
    if settings is not None and settings.map_image_path:
        referenced_paths.add(settings.map_image_path)

    nodes = GardenNode.query.filter_by(site_id=site.id).all()
    node_ids = [node.id for node in nodes]
    for node in nodes:
        if node.hero_image_path:
            referenced_paths.add(node.hero_image_path)
        if node.map_image_path:
            referenced_paths.add(node.map_image_path)

    if node_ids:
        for relative_path, in NodePhoto.query.filter(NodePhoto.node_id.in_(node_ids)).with_entities(NodePhoto.image_path):
            if relative_path:
                referenced_paths.add(relative_path)
        for relative_path, in (
            NodeActivityImage.query.join(NodeActivity)
            .filter(NodeActivity.node_id.in_(node_ids))
            .with_entities(NodeActivityImage.image_path)
        ):
            if relative_path:
                referenced_paths.add(relative_path)

    total = 0
    for relative_path in referenced_paths:
        file_path = relative_upload_to_fs_path(upload_dir, relative_path)
        if file_path.exists() and file_path.is_file():
            total += file_path.stat().st_size
    return total


def storage_quota_summary(*, site=None) -> dict[str, int | None | str]:
    """Return current site and platform quota usage for UI or validation."""
    from .models import GardenSettings, PlatformSettings

    site = site or current_site()
    platform_settings = PlatformSettings.get_or_create()
    site_settings = GardenSettings.get_or_create(site) if site is not None else None

    site_used = site_storage_usage_bytes(site)
    total_used = total_webapp_storage_usage_bytes()
    site_limit_mb = getattr(site_settings, "site_storage_limit_mb", None) if site_settings is not None else None
    total_limit_mb = getattr(platform_settings, "total_webapp_storage_limit_mb", None)
    site_limit = _mb_to_bytes(site_limit_mb)
    total_limit = _mb_to_bytes(total_limit_mb)

    return {
        "site_used_bytes": site_used,
        "site_limit_bytes": site_limit,
        "site_limit_mb": site_limit_mb,
        "site_remaining_bytes": max((site_limit or 0) - site_used, 0) if site_limit is not None else None,
        "site_used_label": _format_bytes(site_used),
        "site_limit_label": _format_bytes(site_limit),
        "site_remaining_label": _format_bytes(max((site_limit or 0) - site_used, 0)) if site_limit is not None else "—",
        "total_used_bytes": total_used,
        "total_limit_bytes": total_limit,
        "total_limit_mb": total_limit_mb,
        "total_remaining_bytes": max((total_limit or 0) - total_used, 0) if total_limit is not None else None,
        "total_used_label": _format_bytes(total_used),
        "total_limit_label": _format_bytes(total_limit),
        "total_remaining_label": _format_bytes(max((total_limit or 0) - total_used, 0)) if total_limit is not None else "—",
    }


def _enforce_storage_limits(saved_file_path: Path, *, enforce_site_limit: bool = True) -> None:
    """Abort one saved upload when it exceeds site or total quotas."""
    from .models import GardenSettings, PlatformSettings

    added_size = saved_file_path.stat().st_size if saved_file_path.exists() else 0
    platform_settings = PlatformSettings.get_or_create()
    total_limit_bytes = _mb_to_bytes(getattr(platform_settings, "total_webapp_storage_limit_mb", None))
    total_used_bytes = total_webapp_storage_usage_bytes()
    if total_limit_bytes is not None and total_used_bytes > total_limit_bytes:
        raise StorageLimitError(
            "Total webapp storage limit exceeded "
            f"({ _format_bytes(total_used_bytes) } used / { _format_bytes(total_limit_bytes) } limit)."
        )

    if not enforce_site_limit:
        return

    site = current_site()
    if site is None:
        return
    site_settings = GardenSettings.get_or_create(site)
    site_limit_bytes = _mb_to_bytes(getattr(site_settings, "site_storage_limit_mb", None))
    if site_limit_bytes is None:
        return
    projected_site_usage = site_storage_usage_bytes(site) + added_size
    if projected_site_usage > site_limit_bytes:
        raise StorageLimitError(
            f"Site storage limit exceeded for '{site.name}' "
            f"({ _format_bytes(projected_site_usage) } projected / { _format_bytes(site_limit_bytes) } limit)."
        )


def save_uploaded_file(
    file_storage: FileStorage | None,
    prefix: str,
    *,
    image_kind: str = "node_photo",
    subfolder: str | None = None,
    enforce_site_limit: bool = True,
) -> str | None:
    """Store an uploaded file in the configured upload directory.

    Parameters:
        file_storage: Uploaded file object provided by Flask/Werkzeug.
        prefix: Prefix added to the generated unique file name.
        image_kind: Logical upload category used to choose compression settings.
        subfolder: Optional relative upload subfolder such as `nodes/12`.
    """
    if file_storage is None or not file_storage.filename:
        return None

    from .models import GardenSettings

    filename = secure_filename(file_storage.filename)
    extension = Path(filename).suffix.lower()
    unique_name = f"{prefix}-{uuid4().hex}{extension}"
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    default_subfolder = "site" if image_kind == "homepage_map" else "misc"
    destination_dir = upload_dir / Path(subfolder or default_subfolder)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / unique_name
    file_storage.save(destination)
    settings = GardenSettings.get_or_create(current_site())
    try:
        optimize_image_file(
            destination,
            max_dimension=max_dimension_for_kind(settings, image_kind),
            jpeg_quality=current_app.config["IMAGE_JPEG_QUALITY"],
            size_threshold=0,
            force=True,
        )
        _enforce_storage_limits(destination, enforce_site_limit=enforce_site_limit)
        return f"uploads/{destination.relative_to(upload_dir).as_posix()}"
    except StorageLimitError:
        destination.unlink(missing_ok=True)
        raise


def save_data_url_upload(
    data_url: str | None,
    prefix: str,
    *,
    image_kind: str = "node_photo",
    subfolder: str | None = None,
    enforce_site_limit: bool = True,
) -> str | None:
    """Store an image received as a browser data URL in the upload directory.

    Parameters:
        data_url: Base64-encoded browser data URL containing the processed image.
        prefix: Prefix added to the generated unique file name.
        image_kind: Logical upload category used to choose compression settings.
        subfolder: Optional relative upload subfolder such as `nodes/12`.
    """
    if not data_url or ";base64," not in data_url:
        return None

    from .models import GardenSettings

    header, encoded_data = data_url.split(";base64,", 1)
    mime_type = header.removeprefix("data:").strip().lower()
    extension = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime_type, ".jpg")

    try:
        payload = base64.b64decode(unquote(encoded_data), validate=True)
    except (ValueError, binascii.Error):
        return None

    unique_name = f"{prefix}-{uuid4().hex}{extension}"
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    default_subfolder = "site" if image_kind == "homepage_map" else "misc"
    destination_dir = upload_dir / Path(subfolder or default_subfolder)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / unique_name
    destination.write_bytes(payload)

    settings = GardenSettings.get_or_create(current_site())
    try:
        optimize_image_file(
            destination,
            max_dimension=max_dimension_for_kind(settings, image_kind),
            jpeg_quality=current_app.config["IMAGE_JPEG_QUALITY"],
            size_threshold=0,
            force=True,
        )
        _enforce_storage_limits(destination, enforce_site_limit=enforce_site_limit)
        return f"uploads/{destination.relative_to(upload_dir).as_posix()}"
    except StorageLimitError:
        destination.unlink(missing_ok=True)
        raise


def permission_required(permission_code: str):
    """Create a decorator that blocks users missing a permission.

    Parameters:
        permission_code: Permission identifier required to access the view.
    """
    def decorator(view):
        """Wrap a view function with a permission check.

        Parameters:
            view: Flask view function being protected.
        """
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            """Abort unauthorized requests before reaching the wrapped view.

            Parameters:
                *args: Positional arguments forwarded to the wrapped view.
                **kwargs: Keyword arguments forwarded to the wrapped view.
            """
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_permission(permission_code, site=current_site()):
                flash("You do not have permission for that action.", "danger")
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def default_node_type(level: int) -> str:
    """Return the default node type for a hierarchy level.

    Parameters:
        level: Depth in the garden hierarchy starting from the root area.
    """
    return LEVEL_TYPE_DEFAULTS.get(level, "custom")
