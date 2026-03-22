from __future__ import annotations

import json
from datetime import datetime, UTC

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

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
    MarkerColor,
    NodeActivity,
    NodeActivityImage,
    NodeExternalLink,
    NodeHomeAssistantEntity,
    NodePhoto,
    TranslationEntry,
    DEFAULT_MARKER_COLOR_BY_NODE_TYPE,
)
from .utils import default_node_type, permission_required, save_uploaded_file
from .translations import DEFAULT_LOCALE, DEFAULT_TRANSLATIONS, SUPPORTED_LOCALES


bp = Blueprint("main", __name__)

MARKER_ICON_SUGGESTIONS = [
    ("mdi-sprout", "Sprout"),
    ("mdi-flower", "Flower"),
    ("mdi-flower-tulip", "Tulip"),
    ("mdi-leaf", "Leaf"),
    ("mdi-seed", "Seed"),
    ("mdi-tree", "Tree"),
    ("mdi-pine-tree", "Pine tree"),
    ("mdi-grass", "Grass"),
    ("mdi-corn", "Corn"),
    ("mdi-shovel", "Shovel"),
    ("mdi-water", "Water"),
    ("mdi-sprinkler", "Sprinkler"),
]


def _settings() -> GardenSettings:
    return GardenSettings.get_or_create()


def _current_locale() -> str:
    supported_locales = {code for code, _label in SUPPORTED_LOCALES}
    if current_user.is_authenticated:
        selected_locale = getattr(current_user, "preferred_locale", None)
        if selected_locale in supported_locales:
            return selected_locale
    return DEFAULT_LOCALE


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


def _default_marker_color_id(node_type: str, marker_colors: list[MarkerColor]) -> int | None:
    desired_sort_order = DEFAULT_MARKER_COLOR_BY_NODE_TYPE.get(node_type)
    if desired_sort_order is not None:
        for marker_color in marker_colors:
            if marker_color.sort_order == desired_sort_order:
                return marker_color.id
    return marker_colors[0].id if marker_colors else None


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def _polygon_from_form(form: NodeForm) -> list[tuple[float, float]]:
    raw_points = [
        (form.area_corner_1_x.data, form.area_corner_1_y.data),
        (form.area_corner_2_x.data, form.area_corner_2_y.data),
        (form.area_corner_3_x.data, form.area_corner_3_y.data),
        (form.area_corner_4_x.data, form.area_corner_4_y.data),
    ]
    if not all(x is not None and y is not None for x, y in raw_points):
        return []
    return [(_clamp_percent(float(x)), _clamp_percent(float(y))) for x, y in raw_points]


def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return (50.0, 50.0)
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _polygon_bounds(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return (18.0, 12.0)
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return (max(max(xs) - min(xs), 0.5), max(max(ys) - min(ys), 0.5))


def _set_default_photo(node: GardenNode, selected_photo: NodePhoto | None) -> None:
    for photo in node.photos:
        photo.is_default = selected_photo is not None and photo.id == selected_photo.id


def _annual_direct_children(node: GardenNode) -> list[GardenNode]:
    return [child for child in node.children if child.life_cycle == "annual"]


def _default_selected_year(node: GardenNode, annual_children: list[GardenNode]) -> int | None:
    current_year = datetime.now(UTC).year
    available_years = sorted(
        {child.effective_cultivation_year for child in annual_children if child.effective_cultivation_year is not None},
        reverse=True,
    )
    if not available_years:
        return None
    if current_year in available_years:
        return current_year
    return available_years[0]


def _clone_scope_candidates(
    node: GardenNode,
    *,
    source_section_id: int | None,
    year_range: int,
    target_year: int,
) -> list[GardenNode]:
    candidate_level = node.level + 1
    lower_year = max(target_year - year_range, 0)
    candidates = GardenNode.query.filter_by(level=candidate_level, life_cycle="annual").all()
    filtered: list[GardenNode] = []

    for candidate in candidates:
        candidate_year = candidate.effective_cultivation_year
        if candidate_year is None or candidate_year >= target_year or candidate_year < lower_year:
            continue
        if candidate.id == node.id:
            continue
        if source_section_id is not None and candidate.section_ancestor.id != source_section_id:
            continue
        filtered.append(candidate)

    return sorted(
        filtered,
        key=lambda candidate: (
            -(candidate.effective_cultivation_year or 0),
            candidate.section_ancestor.title,
            candidate.parent.title if candidate.parent else "",
            candidate.title,
        ),
    )


def _copy_clone_position(source: GardenNode, target: GardenNode, *, preserve_existing: bool = False) -> None:
    if preserve_existing and (
        target.map_x is not None
        or target.map_y is not None
        or target.additional_positions_json
        or any(
            value is not None
            for value in (
                target.area_corner_1_x,
                target.area_corner_1_y,
                target.area_corner_2_x,
                target.area_corner_2_y,
                target.area_corner_3_x,
                target.area_corner_3_y,
                target.area_corner_4_x,
                target.area_corner_4_y,
            )
        )
    ):
        return

    target.map_x = source.map_x
    target.map_y = source.map_y
    target.overlay_shape = source.overlay_shape
    target.overlay_width = source.overlay_width
    target.overlay_height = source.overlay_height
    target.additional_positions_json = source.additional_positions_json
    target.area_corner_1_x = source.area_corner_1_x
    target.area_corner_1_y = source.area_corner_1_y
    target.area_corner_2_x = source.area_corner_2_x
    target.area_corner_2_y = source.area_corner_2_y
    target.area_corner_3_x = source.area_corner_3_x
    target.area_corner_3_y = source.area_corner_3_y
    target.area_corner_4_x = source.area_corner_4_x
    target.area_corner_4_y = source.area_corner_4_y


def _clone_cultivation_node(source: GardenNode, target_parent: GardenNode, target_year: int) -> GardenNode:
    planting_date = source.planting_date
    if planting_date is not None:
        try:
            planting_date = planting_date.replace(year=target_year)
        except ValueError:
            planting_date = planting_date.replace(year=target_year, day=28)

    clone = GardenNode(
        parent=target_parent,
        cloned_from_node=source,
        level=source.level,
        node_type=source.node_type,
        title=source.title,
        summary=source.summary,
        notes=source.notes,
        quantity=source.quantity,
        life_cycle=source.life_cycle,
        cultivation_year=target_year if source.life_cycle == "annual" else source.cultivation_year,
        planting_date=planting_date,
        death_year=None,
        hero_image_path=None,
        image_display_mode=source.image_display_mode,
        image_focus_x=source.image_focus_x,
        image_focus_y=source.image_focus_y,
        map_x=source.map_x,
        map_y=source.map_y,
        overlay_shape=source.overlay_shape,
        overlay_width=source.overlay_width,
        overlay_height=source.overlay_height,
        additional_positions_json=source.additional_positions_json,
        area_corner_1_x=source.area_corner_1_x,
        area_corner_1_y=source.area_corner_1_y,
        area_corner_2_x=source.area_corner_2_x,
        area_corner_2_y=source.area_corner_2_y,
        area_corner_3_x=source.area_corner_3_x,
        area_corner_3_y=source.area_corner_3_y,
        area_corner_4_x=source.area_corner_4_x,
        area_corner_4_y=source.area_corner_4_y,
        marker_color=source.marker_color,
        hotspot_color=source.hotspot_color,
        marker_icon=source.marker_icon,
        geo_lat=None,
        geo_lng=None,
        sort_order=source.sort_order,
        is_published=source.is_published,
    )
    db.session.add(clone)
    db.session.flush()
    _copy_clone_position(source, clone)

    for link in source.external_links:
        db.session.add(
            NodeExternalLink(
                node=clone,
                link_type=link.link_type,
                label=link.label,
                url=link.url,
                description=link.description,
            )
        )

    for child in source.children:
        _clone_cultivation_node(child, clone, target_year)

    return clone


def _point_positions_from_json(value: str | None) -> list[tuple[float, float]]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return []

    if not isinstance(payload, list):
        return []

    positions: list[tuple[float, float]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        x = item.get("x")
        y = item.get("y")
        if x is None or y is None:
            continue
        try:
            positions.append((_clamp_percent(float(x)), _clamp_percent(float(y))))
        except (TypeError, ValueError):
            continue
    return positions


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
    annual_children = _annual_direct_children(node)
    selected_year = request.args.get("year", type=int)
    if annual_children and selected_year is None:
        selected_year = _default_selected_year(node, annual_children)
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
        selected_photo = node.default_photo or ordered_photos[0]

    current_image_path = (
        selected_photo.image_path
        if selected_photo is not None
        else node.display_image
    )
    visible_children = [
        child
        for child in node.children
        if (show_dead_children or not child.is_dead)
        and (
            child.life_cycle != "annual"
            or selected_year is None
            or child.effective_cultivation_year == selected_year
        )
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
    current_year = datetime.now(UTC).year
    available_cultivation_years = sorted(
        {child.effective_cultivation_year for child in annual_children if child.effective_cultivation_year is not None},
        reverse=True,
    )
    source_sections = GardenNode.query.filter_by(level=2).order_by(GardenNode.title).all()
    current_section = node.section_ancestor
    selected_source_section_id = request.args.get("clone_section_id", type=int)
    if selected_source_section_id is None and node.level > 1:
        selected_source_section_id = current_section.id
    year_range = request.args.get("clone_year_range", type=int) or 1
    clone_candidates = (
        _clone_scope_candidates(
            node,
            source_section_id=selected_source_section_id,
            year_range=year_range,
            target_year=current_year,
        )
        if node.level in {2, 3}
        else []
    )
    cultivation_history = (
        node.lineage_nodes()
        if node.life_cycle == "annual" and (node.cloned_from_node is not None or node.cloned_nodes)
        else []
    )
    return render_template(
        "node_detail.html",
        node=node,
        visible_children=visible_children,
        show_dead_children=show_dead_children,
        selected_year=selected_year,
        available_cultivation_years=available_cultivation_years,
        current_year=current_year,
        clone_candidates=clone_candidates,
        selected_source_section_id=selected_source_section_id,
        source_sections=source_sections,
        clone_year_range=year_range,
        cultivation_history=cultivation_history,
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


@bp.route("/nodes/<int:node_id>/clone-cultivations", methods=["POST"])
@login_required
@permission_required("manage_content")
def clone_cultivations(node_id: int):
    node = GardenNode.query.get_or_404(node_id)
    if node.level not in {2, 3}:
        flash("Cultivation cloning is only available on sections and beds.", "warning")
        return redirect(url_for("main.node_detail", node_id=node.id))

    selected_ids = request.form.getlist("candidate_ids")
    target_year = request.form.get("target_year", type=int) or datetime.now(UTC).year
    source_section_id = request.form.get("source_section_id", type=int)
    year_range = request.form.get("year_range", type=int) or 1

    allowed_candidates = {
        candidate.id: candidate
        for candidate in _clone_scope_candidates(
            node,
            source_section_id=source_section_id,
            year_range=year_range,
            target_year=target_year,
        )
    }

    cloned_count = 0
    for raw_id in selected_ids:
        try:
            source_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        source = allowed_candidates.get(source_id)
        if source is None:
            continue

        duplicate = GardenNode.query.filter_by(
            parent_id=node.id,
            cloned_from_node_id=source.id,
            cultivation_year=target_year,
        ).first()
        if duplicate is not None:
            _copy_clone_position(source, duplicate, preserve_existing=True)
            continue

        _clone_cultivation_node(source, node, target_year)
        cloned_count += 1

    db.session.commit()
    if cloned_count:
        flash(f"Cloned {cloned_count} cultivation(s) into {target_year}.", "success")
    else:
        flash("No cultivations were cloned. They may already exist in the selected year.", "warning")

    return redirect(
        url_for(
            "main.node_detail",
            node_id=node.id,
            year=target_year,
            clone_section_id=source_section_id,
            clone_year_range=year_range,
        )
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
    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
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
    form.marker_color_id.choices = [
        (marker_color.id, f"{marker_color.name} ({marker_color.hex_value})")
        for marker_color in marker_colors
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
        form.additional_positions_json.data = "[]"
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
        default_marker_color_id = _default_marker_color_id(form.node_type.data, marker_colors)
        if default_marker_color_id is not None:
            form.marker_color_id.data = default_marker_color_id
        if level in {3, 4}:
            form.life_cycle.data = ""
    elif request.method == "GET" and node is not None:
        form.additional_positions_json.data = json.dumps(
            [{"x": x, "y": y} for x, y in node.point_positions]
        )
        form.cultivation_year.data = node.effective_cultivation_year
        if form.marker_color_id.data is None:
            default_marker_color_id = _default_marker_color_id(node.node_type, marker_colors)
            if default_marker_color_id is not None:
                form.marker_color_id.data = default_marker_color_id

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
            node.cultivation_year = None
            node.planting_date = None
            node.death_year = None
        else:
            node.quantity = form.quantity.data or 1
            node.life_cycle = form.life_cycle.data or None
            node.cultivation_year = (
                form.cultivation_year.data
                if node.life_cycle == "annual"
                else None
            )
            node.planting_date = form.planting_date.data
            node.death_year = form.death_year.data
            if node.life_cycle == "annual" and node.cultivation_year is None and node.planting_date is not None:
                node.cultivation_year = node.planting_date.year
        node.image_display_mode = form.image_display_mode.data
        node.image_focus_x = float(form.image_focus_x.data) if form.image_focus_x.data is not None else 50.0
        node.image_focus_y = float(form.image_focus_y.data) if form.image_focus_y.data is not None else 50.0
        node.overlay_shape = form.overlay_shape.data
        marker_color = db.session.get(MarkerColor, form.marker_color_id.data)
        node.marker_color = marker_color
        node.hotspot_color = marker_color.hex_value if marker_color is not None else "#f28c28"
        marker_icon = (form.marker_icon.data or "").strip()
        if marker_icon and not marker_icon.startswith("mdi-"):
            marker_icon = f"mdi-{marker_icon}"
        node.marker_icon = marker_icon or None
        node.sort_order = form.sort_order.data or 0
        node.is_published = form.is_published.data
        polygon_points = _polygon_from_form(form) if parent is not None and form.overlay_shape.data == "area" else []
        if parent is not None and form.overlay_shape.data == "area" and polygon_points:
            node.overlay_width, node.overlay_height = _polygon_bounds(polygon_points)
            node.map_x, node.map_y = _polygon_centroid(polygon_points)
            (
                node.area_corner_1_x,
                node.area_corner_1_y,
                node.area_corner_2_x,
                node.area_corner_2_y,
                node.area_corner_3_x,
                node.area_corner_3_y,
                node.area_corner_4_x,
                node.area_corner_4_y,
            ) = (
                polygon_points[0][0],
                polygon_points[0][1],
                polygon_points[1][0],
                polygon_points[1][1],
                polygon_points[2][0],
                polygon_points[2][1],
                polygon_points[3][0],
                polygon_points[3][1],
            )
        else:
            node.overlay_width = float(form.overlay_width.data) if form.overlay_width.data is not None else 18.0
            node.overlay_height = float(form.overlay_height.data) if form.overlay_height.data is not None else 12.0
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
            node.area_corner_1_x = None
            node.area_corner_1_y = None
            node.area_corner_2_x = None
            node.area_corner_2_y = None
            node.area_corner_3_x = None
            node.area_corner_3_y = None
            node.area_corner_4_x = None
            node.area_corner_4_y = None
            if parent is not None and form.overlay_shape.data == "point":
                point_positions = _point_positions_from_json(form.additional_positions_json.data)
                if not point_positions and form.map_x.data is not None and form.map_y.data is not None:
                    point_positions = [
                        (_clamp_percent(float(form.map_x.data)), _clamp_percent(float(form.map_y.data)))
                    ]
                if point_positions:
                    node.map_x = point_positions[0][0]
                    node.map_y = point_positions[0][1]
                    node.additional_positions_json = (
                        json.dumps(
                            [{"x": x, "y": y} for x, y in point_positions[1:]]
                        )
                        if len(point_positions) > 1
                        else None
                    )
                else:
                    node.map_x = None
                    node.map_y = None
                    node.additional_positions_json = None
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
        marker_colors=marker_colors,
        marker_icon_suggestions=MARKER_ICON_SUGGESTIONS,
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
                is_default=node.default_photo is None and uploaded_count == 0,
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
            quantity_kg=float(form.quantity_kg.data) if form.quantity_kg.data is not None else None,
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
        form.quantity_kg.data = activity.quantity_kg
        form.description.data = activity.description

    if form.validate_on_submit():
        activity.activity_type_id = form.activity_type_id.data
        activity.happened_on = form.happened_on.data
        activity.quantity_kg = float(form.quantity_kg.data) if form.quantity_kg.data is not None else None
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
        form.is_default.data = photo.is_default

    if form.validate_on_submit():
        photo.title = form.title.data.strip()
        photo.caption = form.caption.data.strip() if form.caption.data else None
        photo.taken_at = datetime.combine(form.taken_at.data, datetime.min.time(), tzinfo=UTC)
        if form.is_default.data:
            _set_default_photo(photo.node, photo)
        elif photo.is_default and any(candidate.id != photo.id for candidate in photo.node.photos):
            photo.is_default = False
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
    node = photo.node
    form = DeleteForm()
    if form.validate_on_submit():
        was_default = photo.is_default
        db.session.delete(photo)
        if was_default:
            remaining_photos = [candidate for candidate in node.photos if candidate.id != photo.id]
            if remaining_photos:
                remaining_default = sorted(
                    remaining_photos,
                    key=lambda candidate: (candidate.taken_at, candidate.id),
                    reverse=True,
                )[0]
                _set_default_photo(node, remaining_default)
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
            url=form.url.data.strip() if form.url.data else "",
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
        link.url = form.url.data.strip() if form.url.data else ""
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
        entity.node.display_image
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
    types = ActivityType.query.order_by(ActivityType.sort_order, ActivityType.name).all()
    form = NodeActivityForm(
        prefix="activity",
        activity_types_by_id={activity_type.id: activity_type for activity_type in types},
    )
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
