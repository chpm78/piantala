from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .home_assistant import HomeAssistantError, sync_entity_catalog, test_connection
from .extensions import db
from .forms import (
    ActionForm,
    ActivityTypeForm,
    DeleteForm,
    HomeAssistantSettingsForm,
    LinkTypeForm,
    MarkerColorForm,
    UserForm,
)
from .models import (
    ActivityType,
    GardenSettings,
    HomeAssistantEntityCatalog,
    HomeAssistantSettings,
    LinkType,
    MarkerColor,
    NodeActivity,
    NodeExternalLink,
    GardenNode,
    Role,
    TranslationEntry,
    User,
)
from .utils import permission_required
from .translations import DEFAULT_LOCALE, SUPPORTED_LOCALES


bp = Blueprint("admin", __name__, url_prefix="/admin")


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
    """Render the user administration list."""
    return render_template(
        "users.html",
        users=User.query.order_by(User.username).all(),
        settings=GardenSettings.get_or_create(),
        ha_settings=HomeAssistantSettings.get_or_create(),
    )


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
