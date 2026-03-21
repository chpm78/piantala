from __future__ import annotations

from datetime import datetime, UTC

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from .extensions import db
from .forms import (
    DeleteForm,
    ExternalLinkForm,
    HomeAssistantEntityForm,
    MapSettingsForm,
    NodeForm,
    NodeActivityForm,
    PhotoEditForm,
    PhotoForm,
)
from .media import extract_exif_taken_at, filename_stem
from .models import (
    ActivityType,
    GardenNode,
    GardenSettings,
    HomeAssistantEntityCatalog,
    HomeAssistantSettings,
    LinkType,
    NodeActivity,
    NodeActivityImage,
    NodeExternalLink,
    NodeHomeAssistantEntity,
    NodePhoto,
    TranslationEntry,
)
from .utils import default_node_type, permission_required, save_uploaded_file
from .translations import DEFAULT_LOCALE, DEFAULT_TRANSLATIONS, SUPPORTED_LOCALES


bp = Blueprint("main", __name__)


def _settings() -> GardenSettings:
    return GardenSettings.get_or_create()


def _current_locale() -> str:
    supported_locales = {code for code, _label in SUPPORTED_LOCALES}
    selected_locale = session.get("locale")
    if selected_locale in supported_locales:
        return selected_locale
    return _settings().default_locale or DEFAULT_LOCALE


def _localized_labels() -> dict[str, str]:
    locale = _current_locale()
    labels = {
        key: values.get(DEFAULT_LOCALE) or next(iter(values.values()))
        for key, values in DEFAULT_TRANSLATIONS.items()
    }

    if locale != DEFAULT_LOCALE:
        for key, values in DEFAULT_TRANSLATIONS.items():
            if values.get(locale):
                labels[key] = values[locale]

    for entry in TranslationEntry.query.filter_by(locale=DEFAULT_LOCALE).all():
        labels[entry.key] = entry.text

    if locale != DEFAULT_LOCALE:
        for entry in TranslationEntry.query.filter_by(locale=locale).all():
            labels[entry.key] = entry.text

    return labels


def _flash_form_errors(form, fallback_message: str) -> None:
    flashed = False
    for field_errors in form.errors.values():
        for error in field_errors:
            flash(error, "danger")
            flashed = True
    if not flashed:
        flash(fallback_message, "danger")


@bp.route("/")
@login_required
@permission_required("view_dashboard")
def index():
    settings = _settings()
    top_level_locations = GardenNode.query.filter_by(parent_id=None).order_by(
        GardenNode.sort_order,
        GardenNode.title,
    ).all()
    geo_locations = [
        {
            "id": location.id,
            "title": location.title,
            "lat": location.geo_lat,
            "lng": location.geo_lng,
            "url": url_for("main.node_detail", node_id=location.id),
        }
        for location in top_level_locations
        if location.has_geo_point
    ]
    return render_template(
        "map.html",
        settings=settings,
        locations=top_level_locations,
        geo_locations=geo_locations,
    )


@bp.route("/settings/map", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def map_settings():
    settings = _settings()
    form = MapSettingsForm(obj=settings)

    if form.validate_on_submit():
        settings.site_name = form.site_name.data.strip()
        settings.welcome_text = form.welcome_text.data.strip()
        settings.color_scheme = form.color_scheme.data
        settings.font_family = form.font_family.data
        settings.default_locale = form.default_locale.data
        settings.map_provider = form.map_provider.data
        settings.google_maps_center_lat = (
            float(form.google_maps_center_lat.data)
            if form.google_maps_center_lat.data is not None
            else None
        )
        settings.google_maps_center_lng = (
            float(form.google_maps_center_lng.data)
            if form.google_maps_center_lng.data is not None
            else None
        )
        settings.google_maps_zoom = form.google_maps_zoom.data or 19

        uploaded_map = save_uploaded_file(form.map_image.data, "map")
        if uploaded_map:
            settings.map_image_path = uploaded_map

        db.session.commit()
        flash("Map settings updated.", "success")
        return redirect(url_for("main.index"))

    return render_template("map_settings.html", form=form, settings=settings)


@bp.route("/language/<locale>")
def set_locale(locale: str):
    supported_locales = {code for code, _label in SUPPORTED_LOCALES}
    if locale in supported_locales:
        session["locale"] = locale
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/nodes/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def create_root_node():
    return _upsert_node(parent=None, node=None)


@bp.route("/nodes/<int:node_id>")
@login_required
@permission_required("view_dashboard")
def node_detail(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    show_dead_children = request.args.get("show_dead") == "1"
    ordered_photos = sorted(
        node.photos,
        key=lambda photo: (photo.taken_at, photo.id),
        reverse=True,
    )
    requested_photo_id = request.args.get("photo", type=int)
    selected_photo = None
    if requested_photo_id is not None:
        selected_photo = next(
            (photo for photo in ordered_photos if photo.id == requested_photo_id),
            None,
        )
    if selected_photo is None and ordered_photos:
        selected_photo = ordered_photos[0]

    current_image_path = (
        selected_photo.image_path
        if selected_photo is not None
        else node.display_image
    )
    visible_children = [
        child
        for child in node.children
        if show_dead_children or not child.is_dead
    ]
    image_children = [
        child
        for child in visible_children
        if child.has_hotspot and child.is_published
    ]
    image_entities = [
        entity
        for entity in node.ha_entities
        if entity.show_on_image and entity.map_x is not None and entity.map_y is not None
    ]
    entity_form = _home_assistant_entity_form()
    catalog_by_entity_id = {
        entry.entity_id: entry
        for entry in HomeAssistantEntityCatalog.query.all()
    }
    return render_template(
        "node_detail.html",
        node=node,
        visible_children=visible_children,
        show_dead_children=show_dead_children,
        current_image_path=current_image_path,
        selected_photo=selected_photo,
        ordered_photos=ordered_photos,
        settings=_settings(),
        image_children=image_children,
        image_entities=image_entities,
        photo_form=PhotoForm(prefix="photo"),
        activity_form=_activity_form(),
        link_form=_external_link_form(),
        entity_form=entity_form,
        ha_catalog_by_entity_id=catalog_by_entity_id,
        ha_is_configured=HomeAssistantSettings.get_or_create().is_configured,
        ha_catalog_count=HomeAssistantEntityCatalog.query.count(),
        delete_form=DeleteForm(),
    )


@bp.route("/nodes/<int:node_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_node(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    return _upsert_node(parent=node.parent, node=node)


@bp.route("/nodes/<int:node_id>/children/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def create_child_node(node_id: int):
    parent = GardenNode.query.get_or_404(node_id)
    if not parent.can_have_children():
        flash("This node is already at level 4 and cannot have children.", "warning")
        return redirect(url_for("main.node_detail", node_id=parent.id))
    return _upsert_node(parent=parent, node=None)


def _upsert_node(parent: GardenNode | None, node: GardenNode | None):
    level = 1 if parent is None else parent.level + 1
    settings = _settings()
    use_geo_map = parent is None and settings.map_provider in {
        "google",
        "openstreetmap",
        "opentopomap",
    }
    if level > 4:
        flash("Nodes can only go down to level 4.", "danger")
        return redirect(url_for("main.index"))

    form = NodeForm(obj=node)
    labels = _localized_labels()
    form.node_type.choices = [
        ("area", labels.get("node.type_area", "Area")),
        ("section", labels.get("node.type_section", "Section")),
        ("bed", labels.get("node.type_bed", "Bed")),
        ("plant", labels.get("node.type_plant", "Plant")),
        ("custom", labels.get("node.type_custom", "Custom")),
    ]
    form.image_display_mode.choices = [
        ("contain", labels.get("node.display_contain", "Show full image")),
        ("cover", labels.get("node.display_cover", "Crop to fill")),
    ]
    form.overlay_shape.choices = [
        ("point", labels.get("node.shape_point", "Point")),
        ("area", labels.get("node.shape_area", "Area")),
    ]
    form.life_cycle.choices = [
        ("", labels.get("node.not_set", "Not set")),
        ("annual", labels.get("node.annual", "Annual")),
        ("perennial", labels.get("node.perennial", "Perennial")),
    ]
    if request.method == "GET" and node is None:
        form.node_type.data = default_node_type(level)
        form.image_display_mode.data = "contain"
        form.image_focus_x.data = 50
        form.image_focus_y.data = 50
        form.quantity.data = 1
        form.overlay_shape.data = "point"
        form.overlay_width.data = 18
        form.overlay_height.data = 12
        form.is_published.data = True
        form.sort_order.data = 0
        if level == 1 and not use_geo_map:
            form.map_x.data = 50
            form.map_y.data = 50
        if level > 1:
            form.map_x.data = 50
            form.map_y.data = 50
        if level == 1 and use_geo_map and settings.google_maps_center_lat is not None:
            form.geo_lat.data = settings.google_maps_center_lat
        if level == 1 and use_geo_map and settings.google_maps_center_lng is not None:
            form.geo_lng.data = settings.google_maps_center_lng
        if level > 1:
            form.hotspot_color.data = "#2f6f4f"
        if level in {3, 4}:
            form.life_cycle.data = ""

    if form.validate_on_submit():
        if node is None:
            node = GardenNode(parent=parent, level=level)
            db.session.add(node)

        node.title = form.title.data.strip()
        node.node_type = form.node_type.data
        node.summary = form.summary.data.strip() if form.summary.data else None
        node.notes = form.notes.data.strip() if form.notes.data else None
        if node.node_type == "section":
            node.quantity = 1
            node.life_cycle = None
            node.planting_date = None
            node.death_year = None
        else:
            node.quantity = form.quantity.data or 1
            node.life_cycle = form.life_cycle.data or None
            node.planting_date = form.planting_date.data
            node.death_year = form.death_year.data
        node.image_display_mode = form.image_display_mode.data
        node.image_focus_x = float(form.image_focus_x.data) if form.image_focus_x.data is not None else 50.0
        node.image_focus_y = float(form.image_focus_y.data) if form.image_focus_y.data is not None else 50.0
        node.overlay_shape = form.overlay_shape.data
        node.overlay_width = float(form.overlay_width.data) if form.overlay_width.data is not None else 18.0
        node.overlay_height = float(form.overlay_height.data) if form.overlay_height.data is not None else 12.0
        node.hotspot_color = form.hotspot_color.data.strip() if form.hotspot_color.data else "#2f6f4f"
        node.sort_order = form.sort_order.data or 0
        node.is_published = form.is_published.data
        node.map_x = (
            float(form.map_x.data)
            if not use_geo_map and form.map_x.data is not None
            else (float(form.map_x.data) if level > 1 and form.map_x.data is not None else None)
        )
        node.map_y = (
            float(form.map_y.data)
            if not use_geo_map and form.map_y.data is not None
            else (float(form.map_y.data) if level > 1 and form.map_y.data is not None else None)
        )
        node.geo_lat = (
            float(form.geo_lat.data)
            if level == 1 and use_geo_map and form.geo_lat.data is not None
            else None
        )
        node.geo_lng = (
            float(form.geo_lng.data)
            if level == 1 and use_geo_map and form.geo_lng.data is not None
            else None
        )

        uploaded_image = save_uploaded_file(form.hero_image.data, f"node-{level}")
        if uploaded_image:
            node.hero_image_path = uploaded_image

        db.session.commit()
        flash("Node saved.", "success")
        return redirect(url_for("main.node_detail", node_id=node.id))

    return render_template(
        "node_form.html",
        form=form,
        node=node,
        parent=parent,
        level=level,
        settings=settings,
        use_geo_map=use_geo_map,
    )


@bp.route("/nodes/<int:node_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_node(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    parent_id = node.parent_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(node)
        db.session.commit()
        flash("Node deleted.", "success")
    else:
        flash("Delete request was rejected.", "danger")

    if parent_id:
        return redirect(url_for("main.node_detail", node_id=parent_id))
    return redirect(url_for("main.index"))


@bp.route("/nodes/<int:node_id>/photos", methods=["POST"])
@login_required
@permission_required("manage_content")
def add_photo(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    form = PhotoForm(prefix="photo")

    if form.validate_on_submit():
        uploaded_count = 0
        for index, image in enumerate(form.images.data):
            if image is None or not image.filename:
                continue

            taken_at = extract_exif_taken_at(image) or datetime.now(UTC)
            image_path = save_uploaded_file(image, f"photo-{node.id}")
            photo = NodePhoto(
                node=node,
                title=filename_stem(image.filename),
                caption=form.caption.data.strip() if form.caption.data else None,
                image_path=image_path,
                taken_at=taken_at,
                sort_order=index,
            )
            db.session.add(photo)
            uploaded_count += 1
        db.session.commit()
        flash(f"Uploaded {uploaded_count} photo(s).", "success")
    else:
        flash("Photo could not be added. Check the form fields.", "danger")

    return redirect(url_for("main.node_detail", node_id=node.id))


@bp.route("/nodes/<int:node_id>/activities", methods=["POST"])
@login_required
@permission_required("manage_content")
def add_activity(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    form = _activity_form()

    if form.validate_on_submit():
        activity = NodeActivity(
            node=node,
            activity_type_id=form.activity_type_id.data,
            happened_on=form.happened_on.data,
            description=form.description.data.strip(),
        )
        db.session.add(activity)
        db.session.flush()

        for image in form.images.data or []:
            if image is None or not image.filename:
                continue
            image_path = save_uploaded_file(image, f"activity-{activity.id}")
            if not image_path:
                continue
            db.session.add(
                NodeActivityImage(
                    activity=activity,
                    title=filename_stem(image.filename),
                    image_path=image_path,
                )
            )

        db.session.commit()
        flash("Activity added.", "success")
    else:
        flash("Activity could not be added. Check the form fields.", "danger")

    return redirect(url_for("main.node_detail", node_id=node.id))


@bp.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_activity(activity_id: int):
    activity = NodeActivity.query.get_or_404(activity_id)
    form = _activity_form(activity)

    if request.method == "GET":
        form.activity_type_id.data = activity.activity_type_id
        form.happened_on.data = activity.happened_on
        form.description.data = activity.description

    if form.validate_on_submit():
        activity.activity_type_id = form.activity_type_id.data
        activity.happened_on = form.happened_on.data
        activity.description = form.description.data.strip()

        for image in form.images.data or []:
            if image is None or not image.filename:
                continue
            image_path = save_uploaded_file(image, f"activity-{activity.id}")
            if not image_path:
                continue
            db.session.add(
                NodeActivityImage(
                    activity=activity,
                    title=filename_stem(image.filename),
                    image_path=image_path,
                )
            )

        db.session.commit()
        flash("Activity updated.", "success")
        return redirect(url_for("main.node_detail", node_id=activity.node_id))

    return render_template(
        "activity_form.html",
        form=form,
        activity=activity,
        node=activity.node,
        settings=_settings(),
        delete_form=DeleteForm(),
    )


@bp.route("/activities/<int:activity_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_activity(activity_id: int):
    activity = NodeActivity.query.get_or_404(activity_id)
    node_id = activity.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(activity)
        db.session.commit()
        flash("Activity deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/photos/<int:photo_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_photo(photo_id: int):
    photo = NodePhoto.query.get_or_404(photo_id)
    form = PhotoEditForm(obj=photo)

    if request.method == "GET":
        form.taken_at.data = photo.taken_at.date()

    if form.validate_on_submit():
        photo.title = form.title.data.strip()
        photo.caption = form.caption.data.strip() if form.caption.data else None
        photo.taken_at = datetime.combine(form.taken_at.data, datetime.min.time(), tzinfo=UTC)
        photo.sort_order = form.sort_order.data or 0
        db.session.commit()
        flash("Photo updated.", "success")
        return redirect(url_for("main.node_detail", node_id=photo.node_id, photo=photo.id))

    return render_template(
        "photo_form.html",
        form=form,
        photo=photo,
        node=photo.node,
        settings=_settings(),
    )


@bp.route("/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_photo(photo_id: int):
    photo = NodePhoto.query.get_or_404(photo_id)
    node_id = photo.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(photo)
        db.session.commit()
        flash("Photo deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/nodes/<int:node_id>/links", methods=["POST"])
@login_required
@permission_required("manage_content")
def add_link(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    form = _external_link_form()

    if form.validate_on_submit():
        link_type = db.session.get(LinkType, form.link_type_id.data)
        if link_type is None:
            flash("Selected link type was not found.", "danger")
            return redirect(url_for("main.node_detail", node_id=node.id))
        link = NodeExternalLink(
            node=node,
            link_type=link_type,
            label=form.label.data.strip() if form.label.data else "",
            url=form.url.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
        )
        db.session.add(link)
        db.session.commit()
        flash("Link added.", "success")
    else:
        _flash_form_errors(form, "Link could not be added. Check the URL and required fields.")

    return redirect(url_for("main.node_detail", node_id=node.id))


@bp.route("/links/<int:link_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_link(link_id: int):
    link = NodeExternalLink.query.get_or_404(link_id)
    node_id = link.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(link)
        db.session.commit()
        flash("Link deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/links/<int:link_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_link(link_id: int):
    link = NodeExternalLink.query.get_or_404(link_id)
    form = _external_link_form()

    if request.method == "GET":
        form.link_type_id.data = link.link_type_id
        form.label.data = link.label
        form.url.data = link.url
        form.description.data = link.description

    if form.validate_on_submit():
        link_type = db.session.get(LinkType, form.link_type_id.data)
        if link_type is None:
            flash("Selected link type was not found.", "danger")
            return redirect(url_for("main.node_detail", node_id=link.node_id))

        link.link_type = link_type
        link.label = form.label.data.strip() if form.label.data else ""
        link.url = form.url.data.strip()
        link.description = form.description.data.strip() if form.description.data else None
        db.session.commit()
        flash("Link updated.", "success")
        return redirect(url_for("main.node_detail", node_id=link.node_id))

    return render_template(
        "external_link_form.html",
        form=form,
        link=link,
        node=link.node,
        settings=_settings(),
    )


@bp.route("/nodes/<int:node_id>/entities", methods=["POST"])
@login_required
@permission_required("manage_content")
def add_entity(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    form = _home_assistant_entity_form()

    if form.validate_on_submit():
        catalog_entry = db.session.get(HomeAssistantEntityCatalog, form.discovered_entity.data)
        if catalog_entry is None:
            flash("Selected Home Assistant entity was not found. Re-sync the catalog.", "danger")
            return redirect(url_for("main.node_detail", node_id=node.id))
        existing_link = NodeHomeAssistantEntity.query.filter_by(
            node_id=node.id,
            entity_id=catalog_entry.entity_id,
        ).first()
        if existing_link:
            flash("That Home Assistant entity is already linked to this node.", "warning")
            return redirect(url_for("main.node_detail", node_id=node.id))

        derived_label = (
            form.label.data.strip()
            if form.label.data
            else (catalog_entry.friendly_name or catalog_entry.entity_id)
        )
        entity = NodeHomeAssistantEntity(
            node=node,
            label=derived_label,
            entity_id=catalog_entry.entity_id,
            current_value=catalog_entry.state,
            unit_of_measurement=catalog_entry.unit_of_measurement,
            notes=form.notes.data.strip() if form.notes.data else None,
            show_on_image=form.show_on_image.data,
            map_x=float(form.map_x.data) if form.map_x.data is not None else None,
            map_y=float(form.map_y.data) if form.map_y.data is not None else None,
            last_synced_at=datetime.now(UTC),
        )
        db.session.add(entity)
        db.session.commit()
        flash("Home Assistant entity added.", "success")
    else:
        flash("Entity could not be added. Sync Home Assistant entities and choose one from the list.", "danger")

    return redirect(url_for("main.node_detail", node_id=node.id))


@bp.route("/entities/<int:entity_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_entity(entity_id: int):
    entity = NodeHomeAssistantEntity.query.get_or_404(entity_id)
    node_id = entity.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(entity)
        db.session.commit()
        flash("Entity deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/entities/<int:entity_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_entity(entity_id: int):
    entity = NodeHomeAssistantEntity.query.get_or_404(entity_id)
    form = _home_assistant_entity_form()

    if request.method == "GET":
        catalog_entry = HomeAssistantEntityCatalog.query.filter_by(entity_id=entity.entity_id).first()
        if catalog_entry is not None:
            form.discovered_entity.data = catalog_entry.id
        form.label.data = entity.label
        form.show_on_image.data = entity.show_on_image
        form.map_x.data = entity.map_x if entity.map_x is not None else 50
        form.map_y.data = entity.map_y if entity.map_y is not None else 50
        form.notes.data = entity.notes

    if form.validate_on_submit():
        catalog_entry = db.session.get(HomeAssistantEntityCatalog, form.discovered_entity.data)
        if catalog_entry is None:
            flash("Selected Home Assistant entity was not found. Re-sync the catalog.", "danger")
            return redirect(url_for("main.node_detail", node_id=entity.node_id))

        existing_link = NodeHomeAssistantEntity.query.filter(
            NodeHomeAssistantEntity.node_id == entity.node_id,
            NodeHomeAssistantEntity.entity_id == catalog_entry.entity_id,
            NodeHomeAssistantEntity.id != entity.id,
        ).first()
        if existing_link:
            flash("That Home Assistant entity is already linked to this node.", "warning")
            return redirect(url_for("main.node_detail", node_id=entity.node_id))

        entity.entity_id = catalog_entry.entity_id
        entity.label = (
            form.label.data.strip()
            if form.label.data
            else (catalog_entry.friendly_name or catalog_entry.entity_id)
        )
        entity.current_value = catalog_entry.state
        entity.unit_of_measurement = catalog_entry.unit_of_measurement
        entity.notes = form.notes.data.strip() if form.notes.data else None
        entity.show_on_image = form.show_on_image.data
        entity.map_x = float(form.map_x.data) if form.map_x.data is not None else None
        entity.map_y = float(form.map_y.data) if form.map_y.data is not None else None
        entity.last_synced_at = datetime.now(UTC)
        db.session.commit()
        flash("Home Assistant entity updated.", "success")
        return redirect(url_for("main.node_detail", node_id=entity.node_id))

    current_image_path = (
        entity.node.latest_photo.image_path
        if entity.node.latest_photo is not None
        else entity.node.display_image
    )
    return render_template(
        "entity_form.html",
        form=form,
        entity=entity,
        node=entity.node,
        current_image_path=current_image_path,
        settings=_settings(),
    )


def _home_assistant_entity_form() -> HomeAssistantEntityForm:
    form = HomeAssistantEntityForm(prefix="entity")
    catalog_entries = HomeAssistantEntityCatalog.query.order_by(
        HomeAssistantEntityCatalog.domain,
        HomeAssistantEntityCatalog.friendly_name,
        HomeAssistantEntityCatalog.entity_id,
    ).all()
    form.discovered_entity.choices = [(0, "Select a Home Assistant entity")] + [
        (
            entry.id,
            _entity_choice_label(entry),
        )
        for entry in catalog_entries
    ]
    if request.method == "GET":
        form.map_x.data = 50
        form.map_y.data = 50
    return form


def _activity_form(activity: NodeActivity | None = None) -> NodeActivityForm:
    form = NodeActivityForm(prefix="activity")
    types = ActivityType.query.order_by(ActivityType.sort_order, ActivityType.name).all()
    form.activity_type_id.choices = [(activity_type.id, activity_type.name) for activity_type in types]
    if request.method == "GET":
        form.happened_on.data = activity.happened_on if activity is not None else datetime.now(UTC).date()
    return form


def _external_link_form() -> ExternalLinkForm:
    link_types = LinkType.query.order_by(LinkType.sort_order, LinkType.name).all()
    form = ExternalLinkForm(
        prefix="link",
        link_types_by_id={link_type.id: link_type for link_type in link_types},
    )
    locale = _current_locale()
    form.link_type_id.choices = [
        (link_type.id, link_type.localized_name(locale))
        for link_type in link_types
    ]
    return form


def _entity_choice_label(entry: HomeAssistantEntityCatalog) -> str:
    name = entry.friendly_name or entry.entity_id
    state = entry.state or "unknown"
    unit = f" {entry.unit_of_measurement}" if entry.unit_of_measurement else ""
    return f"{name} [{entry.entity_id}] - {state}{unit}"
