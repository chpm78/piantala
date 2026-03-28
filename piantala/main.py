from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .forms import (
    DeleteForm,
    ExternalLinkForm,
    HomeAssistantEntityForm,
    IrrigationZoneForm,
    MapSettingsForm,
    NodeImageEditForm,
    NodeForm,
    NodeActivityForm,
    PhotoEditForm,
    PhotoForm,
)
from .home_assistant import HomeAssistantError, fetch_entity_history
from .media import extract_exif_taken_at, filename_stem, remove_unreferenced_uploads
from .models import (
    ActivityType,
    DEFAULT_IRRIGATION_ZONE_COLOR,
    DEFAULT_IRRIGATION_ZONE_TEXTURE,
    GardenNode,
    GardenSettings,
    HomeAssistantEntityCatalog,
    HomeAssistantSettings,
    IRRIGATION_ZONE_COLORS,
    IRRIGATION_ZONE_TEXTURES,
    LinkType,
    MarkerColor,
    NodeActivity,
    NodeActivityImage,
    NodeExternalLink,
    NodeHomeAssistantEntity,
    NodeIrrigationZone,
    NodePhoto,
    TranslationEntry,
    DEFAULT_MARKER_COLOR_BY_NODE_TYPE,
)
from .utils import default_node_type, permission_required, save_data_url_upload, save_uploaded_file
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
    """Return the singleton site-wide settings record."""
    return GardenSettings.get_or_create()


def _upload_directory() -> Path:
    """Return the absolute upload directory configured for the current app."""
    from flask import current_app

    return Path(current_app.config["UPLOAD_FOLDER"])


def _collect_activity_image_paths(activity: NodeActivity) -> set[str]:
    """Collect image paths linked to an activity.

    Parameters:
        activity: Activity whose uploaded images should be collected.
    """
    return {image.image_path for image in activity.images if image.image_path}


def _collect_node_image_paths(node: GardenNode) -> set[str]:
    """Collect every uploaded image path reachable from a node subtree.

    Parameters:
        node: Root node whose direct and nested uploaded images should be collected.
    """
    image_paths: set[str] = set()

    def visit(current_node: GardenNode) -> None:
        if current_node.hero_image_path:
            image_paths.add(current_node.hero_image_path)
        if current_node.map_image_path:
            image_paths.add(current_node.map_image_path)
        for photo in current_node.photos:
            if photo.image_path:
                image_paths.add(photo.image_path)
        for activity in current_node.activities:
            image_paths.update(_collect_activity_image_paths(activity))
        for child in current_node.children:
            visit(child)

    visit(node)
    return image_paths


def _current_locale() -> str:
    """Return the locale that should be used for the current request."""
    supported_locales = {code for code, _label in SUPPORTED_LOCALES}
    if current_user.is_authenticated:
        selected_locale = getattr(current_user, "preferred_locale", None)
        if selected_locale in supported_locales:
            return selected_locale
    return DEFAULT_LOCALE


def _localized_labels() -> dict[str, str]:
    """Build the translation map for the active locale."""
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
    """Flash all form validation errors or a fallback message when none are attached.

    Parameters:
        form: The submitted form that may contain validation errors.
        fallback_message: Message to show when the form did not collect field errors.
    """
    flashed = False
    for field_errors in form.errors.values():
        for error in field_errors:
            flash(error, "danger")
            flashed = True
    if not flashed:
        flash(fallback_message, "danger")


def _default_marker_color_id(node_type: str, marker_colors: list[MarkerColor]) -> int | None:
    """Return the default marker color id for a node type.

    Parameters:
        node_type: Node classification such as plant, bed, or section.
        marker_colors: Available marker colors ordered for user selection.
    """
    desired_sort_order = DEFAULT_MARKER_COLOR_BY_NODE_TYPE.get(node_type)
    if desired_sort_order is not None:
        for marker_color in marker_colors:
            if marker_color.sort_order == desired_sort_order:
                return marker_color.id
    return marker_colors[0].id if marker_colors else None


def _clamp_percent(value: float) -> float:
    """Keep a percentage value inside the 0-100 range.

    Parameters:
        value: Percentage value to normalize.
    """
    return max(0.0, min(100.0, value))


def _polygon_from_coordinate_pairs(
    raw_points: list[tuple[object | None, object | None]],
) -> list[tuple[float, float]]:
    """Normalize polygon corner pairs into percentage coordinates.

    Parameters:
        raw_points: Corner pairs read from form fields or other raw inputs.
    """
    if not all(x is not None and y is not None for x, y in raw_points):
        return []
    return [(_clamp_percent(float(x)), _clamp_percent(float(y))) for x, y in raw_points]


def _polygon_from_form(form: NodeForm) -> list[tuple[float, float]]:
    """Read a four-corner area polygon from the node form.

    Parameters:
        form: Submitted node form containing the hidden corner fields.
    """
    return _polygon_from_coordinate_pairs(
        [
            (form.area_corner_1_x.data, form.area_corner_1_y.data),
            (form.area_corner_2_x.data, form.area_corner_2_y.data),
            (form.area_corner_3_x.data, form.area_corner_3_y.data),
            (form.area_corner_4_x.data, form.area_corner_4_y.data),
        ]
    )


def _polygon_from_irrigation_form(form: IrrigationZoneForm) -> list[tuple[float, float]]:
    """Read a four-corner irrigation zone polygon from the irrigation form.

    Parameters:
        form: Submitted irrigation zone form containing hidden corner fields.
    """
    return _polygon_from_coordinate_pairs(
        [
            (form.area_corner_1_x.data, form.area_corner_1_y.data),
            (form.area_corner_2_x.data, form.area_corner_2_y.data),
            (form.area_corner_3_x.data, form.area_corner_3_y.data),
            (form.area_corner_4_x.data, form.area_corner_4_y.data),
        ]
    )


def _subzone_polygons_from_irrigation_form(form: IrrigationZoneForm) -> list[list[dict[str, float]]]:
    """Read additional irrigation polygons from the form payload.

    Parameters:
        form: Submitted irrigation zone form containing the polygons JSON field.
    """
    try:
        raw_polygons = json.loads(form.subzone_rectangles_json.data or "[]")
    except (TypeError, ValueError):
        raw_polygons = []

    polygons: list[list[dict[str, float]]] = []
    if not isinstance(raw_polygons, list):
        return polygons

    for raw_polygon in raw_polygons:
        points = raw_polygon.get("points") if isinstance(raw_polygon, dict) else raw_polygon
        if not isinstance(points, list) or len(points) != 4:
            continue

        polygon: list[dict[str, float]] = []
        valid = True
        for point in points:
            if not isinstance(point, dict):
                valid = False
                break
            try:
                polygon.append(
                    {
                        "x": _clamp_percent(float(point.get("x"))),
                        "y": _clamp_percent(float(point.get("y"))),
                    }
                )
            except (TypeError, ValueError):
                valid = False
                break
        if valid:
            polygons.append(polygon)
    return polygons


def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the center point of a polygon.

    Parameters:
        points: Polygon points stored as percentage-based image coordinates.
    """
    if not points:
        return (50.0, 50.0)
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _polygon_bounds(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the width and height of a polygon's bounding box.

    Parameters:
        points: Polygon points stored as percentage-based image coordinates.
    """
    if not points:
        return (18.0, 12.0)
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return (max(max(xs) - min(xs), 0.5), max(max(ys) - min(ys), 0.5))


def _history_days_from_range(range_key: str) -> int:
    """Return the day count associated with a Home Assistant history range key.

    Parameters:
        range_key: Compact range identifier from the query string.
    """
    return 7 if range_key == "7d" else 1


def _parse_history_timestamp(value: str | None) -> datetime | None:
    """Parse a Home Assistant history timestamp into a timezone-aware datetime.

    Parameters:
        value: ISO timestamp string returned by Home Assistant.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_entity_history_chart(
    history_points: list[dict[str, str | None]],
    *,
    range_key: str,
) -> dict[str, object] | None:
    """Convert Home Assistant state history into chart-ready numeric samples.

    Parameters:
        history_points: Raw history points returned by the Home Assistant API.
        range_key: Selected range key such as ``1d`` or ``7d``.
    """
    samples: list[tuple[datetime, float]] = []
    for point in history_points:
        timestamp = _parse_history_timestamp(point.get("last_changed"))
        if timestamp is None:
            continue
        try:
            numeric_state = float(point.get("state") or "")
        except (TypeError, ValueError):
            continue
        samples.append((timestamp, numeric_state))

    if not samples:
        return None

    samples.sort(key=lambda item: item[0])
    start_at = samples[0][0]
    end_at = samples[-1][0]
    min_value = min(value for _timestamp, value in samples)
    max_value = max(value for _timestamp, value in samples)

    def _format_value(raw_value: float) -> str:
        if abs(raw_value - round(raw_value)) < 1e-9:
            return str(int(round(raw_value)))
        return f"{raw_value:.2f}".rstrip("0").rstrip(".")

    if range_key == "7d":
        time_format = "%d/%m"
    else:
        time_format = "%d/%m %H:%M"

    return {
        "min_value": _format_value(min_value),
        "max_value": _format_value(max_value),
        "latest_value": _format_value(samples[-1][1]),
        "start_label": start_at.astimezone().strftime(time_format),
        "end_label": end_at.astimezone().strftime(time_format),
        "sample_count": len(samples),
        "range_key": range_key,
        "samples": [
            {
                "ts": timestamp.astimezone(UTC).isoformat(),
                "value": value,
            }
            for timestamp, value in samples
        ],
    }


def _load_entity_history_payload(
    node: GardenNode,
    *,
    range_key: str,
) -> tuple[dict[str, dict[str, object] | None], str | None]:
    """Load chart payloads for all Home Assistant entities linked to a node.

    Parameters:
        node: Node whose Home Assistant entities should be charted.
        range_key: Selected time range key such as ``1d`` or ``7d``.
    """
    ha_settings = HomeAssistantSettings.get_or_create()
    if not node.ha_entities or not ha_settings.is_configured:
        return {}, None

    try:
        history_by_entity = fetch_entity_history(
            ha_settings,
            [entity.entity_id for entity in node.ha_entities],
            days=_history_days_from_range(range_key),
        )
        return {
            entity.entity_id: _build_entity_history_chart(
                history_by_entity.get(entity.entity_id, []),
                range_key=range_key,
            )
            for entity in node.ha_entities
        }, None
    except HomeAssistantError as exc:
        return {}, str(exc)


def _set_default_photo(node: GardenNode, selected_photo: NodePhoto | None) -> None:
    """Mark one photo as default and clear the flag on all other node photos.

    Parameters:
        node: Node whose photo collection should be updated.
        selected_photo: Photo that should become the default image, if any.
    """
    for photo in node.photos:
        photo.is_default = selected_photo is not None and photo.id == selected_photo.id


def _annual_direct_children(node: GardenNode) -> list[GardenNode]:
    """Return annual children directly below a node.

    Parameters:
        node: Parent node whose immediate children should be inspected.
    """
    return [child for child in node.children if child.life_cycle == "annual"]


def _clone_scope_candidates(
    node: GardenNode,
    *,
    source_section_id: int | None,
    year_range: int,
    target_year: int,
) -> list[GardenNode]:
    """Return annual cultivation nodes that can be cloned into a target year.

    Parameters:
        node: Parent node that will receive the cloned cultivation.
        source_section_id: Optional section filter for narrowing clone candidates.
        year_range: Number of years back from the target year to include.
        target_year: Cultivation year that the new clone will belong to.
    """
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
    """Copy hotspot or area placement from one node to another.

    Parameters:
        source: Node that already contains the desired placement data.
        target: Node that should receive the copied placement data.
        preserve_existing: When True, keep any existing target placement.
    """
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
    """Clone an annual cultivation subtree into a different cultivation year.

    Parameters:
        source: Existing cultivation node that acts as the template.
        target_parent: Parent node that will own the cloned cultivation.
        target_year: Cultivation year assigned to the cloned annual records.
    """
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
        map_image_path=None,
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
    """Parse additional point positions stored as JSON.

    Parameters:
        value: JSON string containing a list of x/y position dictionaries.
    """
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


def _node_image_role_path(node: GardenNode, image_role: str) -> str | None:
    """Return the stored image path for a legacy node image role.

    Parameters:
        node: Node whose dedicated display or map image is being inspected.
        image_role: Legacy role key, either ``display`` or ``map``.
    """
    if image_role == "map":
        return node.map_image_path
    return node.hero_image_path


def _serialize_manageable_child(child: GardenNode) -> dict[str, object]:
    """Build the client-side position editor payload for one direct child node.

    Parameters:
        child: Child node whose hotspot or area placement should be exposed.
    """
    return {
        "id": child.id,
        "title": child.title,
        "node_type": child.node_type or "custom",
        "overlay_shape": child.overlay_shape or "point",
        "marker_color": child.marker_color_value,
        "marker_icon": child.marker_icon_class or "",
        "points": [{"x": x, "y": y} for x, y in child.point_positions],
        "polygon": [{"x": x, "y": y} for x, y in child.area_polygon_points],
        "cultivation_year": child.effective_cultivation_year,
        "is_dead": child.is_dead,
    }


def _apply_manageable_child_position(child: GardenNode, payload: dict[str, object]) -> None:
    """Apply edited client-side position data back to a child node.

    Parameters:
        child: Child node whose saved placement should be updated.
        payload: Decoded JSON payload posted by the bulk position editor.
    """
    if child.overlay_shape == "area":
        raw_polygon = payload.get("polygon")
        if isinstance(raw_polygon, list):
            polygon_points = _polygon_from_coordinate_pairs(
                [
                    (
                        point.get("x") if isinstance(point, dict) else None,
                        point.get("y") if isinstance(point, dict) else None,
                    )
                    for point in raw_polygon
                ]
            )
            if len(polygon_points) == 4:
                child.overlay_width, child.overlay_height = _polygon_bounds(polygon_points)
                child.map_x, child.map_y = _polygon_centroid(polygon_points)
                child.additional_positions_json = None
                (
                    child.area_corner_1_x,
                    child.area_corner_1_y,
                    child.area_corner_2_x,
                    child.area_corner_2_y,
                    child.area_corner_3_x,
                    child.area_corner_3_y,
                    child.area_corner_4_x,
                    child.area_corner_4_y,
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
        return

    raw_points = payload.get("points")
    if not isinstance(raw_points, list):
        return

    point_positions = _point_positions_from_json(json.dumps(raw_points))
    if not point_positions:
        return

    child.map_x = point_positions[0][0]
    child.map_y = point_positions[0][1]
    child.additional_positions_json = (
        json.dumps([{"x": x, "y": y} for x, y in point_positions[1:]])
        if len(point_positions) > 1
        else None
    )
    child.area_corner_1_x = None
    child.area_corner_1_y = None
    child.area_corner_2_x = None
    child.area_corner_2_y = None
    child.area_corner_3_x = None
    child.area_corner_3_y = None
    child.area_corner_4_x = None
    child.area_corner_4_y = None


@bp.route("/")
@login_required
@permission_required("view_dashboard")
def index():
    """Render the map-first dashboard with top-level locations."""
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
    """Display and save site-wide map and appearance settings."""
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

        uploaded_map = save_data_url_upload(
            form.processed_map_image_data.data,
            "map",
            image_kind="homepage_map",
            subfolder="site",
        ) or save_uploaded_file(
            form.map_image.data,
            "map",
            image_kind="homepage_map",
            subfolder="site",
        )
        if uploaded_map:
            settings.map_image_path = uploaded_map
        settings.homepage_map_max_dimension = form.homepage_map_max_dimension.data
        settings.node_display_max_dimension = form.node_display_max_dimension.data
        settings.node_map_max_dimension = form.node_map_max_dimension.data
        settings.node_photo_max_dimension = form.node_photo_max_dimension.data
        settings.activity_image_max_dimension = form.activity_image_max_dimension.data

        db.session.commit()
        flash("Map settings updated.", "success")
        return redirect(url_for("main.index"))

    return render_template("map_settings.html", form=form, settings=settings)
@bp.route("/nodes/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def create_root_node():
    """Create a new top-level area node."""
    return _upsert_node(parent=None, node=None)


@bp.route("/nodes/<int:node_id>")
@login_required
@permission_required("view_dashboard")
def node_detail(node_id: int):
    """Render a node detail page with children, media, activities, and tools.

    Parameters:
        node_id: Identifier of the node to display.
    """
    node = GardenNode.query.get_or_404(node_id)
    show_dead_children = request.args.get("show_dead") == "1"
    requested_display_mode = request.args.get("display")
    if requested_display_mode in {"irrigation", "cultivations", "both"}:
        display_mode = requested_display_mode
    elif request.args.get("show_irrigation") == "1":
        display_mode = "both"
    else:
        display_mode = "cultivations"
    annual_children = _annual_direct_children(node)
    raw_year = request.args.get("year")
    selected_year = request.args.get("year", type=int) if raw_year not in {None, ""} else None
    available_cultivation_years = sorted(
        {child.effective_cultivation_year for child in annual_children if child.effective_cultivation_year is not None},
        reverse=True,
    )
    if raw_year is None and available_cultivation_years:
        selected_year = available_cultivation_years[0]
    ordered_photos = sorted(
        node.photos,
        key=lambda photo: (photo.taken_at, photo.id),
        reverse=True,
    )
    prospect_photos = node.photos_for_role("prospect")
    map_photos = node.photos_for_role("map")
    gallery_photos = node.photos_for_role("gallery")
    prospect_photo = (
        node.preferred_photo_for_role("prospect")
        or node.preferred_photo_for_role("gallery")
        or node.default_photo
        or node.latest_photo
    )
    map_photo = node.preferred_photo_for_role("map")
    requested_history_range = request.args.get("ha_range")
    ha_history_range = requested_history_range if requested_history_range in {"1d", "7d"} else "1d"
    display_image_path = node.display_image
    navigation_image_path = node.map_view_image
    visible_children = list(node.children)
    image_children = [
        child
        for child in node.children
        if child.has_hotspot and child.is_published
    ]
    image_entities = [
        entity
        for entity in node.ha_entities
        if entity.show_on_image and entity.map_x is not None and entity.map_y is not None
    ]
    image_irrigation_zones = [
        zone
        for zone in node.irrigation_zones
        if zone.area_polygon_points
    ]
    entity_form = _home_assistant_entity_form()
    catalog_by_entity_id = {
        entry.entity_id: entry
        for entry in HomeAssistantEntityCatalog.query.all()
    }
    ha_settings = HomeAssistantSettings.get_or_create()
    ha_history_charts, ha_history_error = _load_entity_history_payload(
        node,
        range_key=ha_history_range,
    )
    current_year = datetime.now(UTC).year
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
        display_image_path=display_image_path,
        navigation_image_path=navigation_image_path,
        ordered_photos=ordered_photos,
        prospect_photo=prospect_photo,
        map_photo=map_photo,
        prospect_photos=prospect_photos,
        map_photos=map_photos,
        gallery_photos=gallery_photos,
        display_mode=display_mode,
        image_irrigation_zones=image_irrigation_zones,
        settings=_settings(),
        image_children=image_children,
        image_entities=image_entities,
        irrigation_zones=node.irrigation_zones,
        link_form=_external_link_form(),
        entity_form=entity_form,
        irrigation_zone_form=_irrigation_zone_form(),
        ha_catalog_by_entity_id=catalog_by_entity_id,
        ha_is_configured=ha_settings.is_configured,
        ha_catalog_count=HomeAssistantEntityCatalog.query.count(),
        ha_history_range=ha_history_range,
        ha_history_charts=ha_history_charts,
        ha_history_error=ha_history_error,
        delete_form=DeleteForm(),
    )


@bp.route("/nodes/<int:node_id>/ha-history")
@login_required
@permission_required("view_dashboard")
def node_entity_history(node_id: int):
    """Return Home Assistant chart payloads for the entities linked to a node.

    Parameters:
        node_id: Identifier of the node whose entity history should be returned.
    """
    node = GardenNode.query.get_or_404(node_id)
    requested_range = request.args.get("range")
    range_key = requested_range if requested_range in {"1d", "7d"} else "1d"
    chart_payload, history_error = _load_entity_history_payload(node, range_key=range_key)
    return jsonify(
        {
            "range": range_key,
            "error": history_error,
            "charts": chart_payload,
        }
    )


@bp.route("/nodes/<int:node_id>/manage-positions", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def manage_cultivation_positions(node_id: int):
    """Edit direct child cultivation placements from a single shared map view.

    Parameters:
        node_id: Identifier of the section or bed whose child positions should be managed.
    """
    node = GardenNode.query.get_or_404(node_id)
    if not node.map_view_image:
        flash("Add a map image to this node before managing cultivation positions.", "warning")
        return redirect(url_for("main.edit_node", node_id=node.id))

    manageable_children = [
        child
        for child in node.children
        if child.has_hotspot
    ]
    if not manageable_children:
        flash("There are no child cultivations with positions to manage yet.", "warning")
        return redirect(url_for("main.node_detail", node_id=node.id))

    form = DeleteForm()
    if form.validate_on_submit():
        try:
            payload = json.loads(request.form.get("positions_payload", "[]"))
        except (TypeError, ValueError):
            payload = []

        if not isinstance(payload, list):
            payload = []

        children_by_id = {child.id: child for child in manageable_children}
        updated_count = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            child_id = item.get("id")
            try:
                child_id = int(child_id)
            except (TypeError, ValueError):
                continue
            child = children_by_id.get(child_id)
            if child is None:
                continue
            _apply_manageable_child_position(child, item)
            updated_count += 1

        db.session.commit()
        flash(f"Updated cultivation positions for {updated_count} item(s).", "success")
        return redirect(url_for("main.node_detail", node_id=node.id))

    return render_template(
        "manage_cultivation_positions.html",
        node=node,
        manageable_children=manageable_children,
        positions_payload=[_serialize_manageable_child(child) for child in manageable_children],
        delete_form=form,
        settings=_settings(),
    )


@bp.route("/nodes/<int:node_id>/clone-cultivations", methods=["POST"])
@login_required
@permission_required("manage_content")
def clone_cultivations(node_id: int):
    """Clone selected annual cultivations into a target year.

    Parameters:
        node_id: Identifier of the section or bed receiving the clones.
    """
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
    """Edit an existing garden node.

    Parameters:
        node_id: Identifier of the node to update.
    """
    node = GardenNode.query.get_or_404(node_id)
    return _upsert_node(parent=node.parent, node=node)


@bp.route("/nodes/<int:node_id>/children/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def create_child_node(node_id: int):
    """Create a new child node under an existing parent.

    Parameters:
        node_id: Identifier of the parent node.
    """
    parent = GardenNode.query.get_or_404(node_id)
    if not parent.can_have_children():
        flash("This node is already at level 4 and cannot have children.", "warning")
        return redirect(url_for("main.node_detail", node_id=parent.id))
    return _upsert_node(parent=parent, node=None)


def _upsert_node(parent: GardenNode | None, node: GardenNode | None):
    """Create or update a node and its placement data.

    Parameters:
        parent: Parent node for a new child, or None for a root node.
        node: Existing node being edited, or None when creating a new node.
    """
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
    form.hero_image_role.choices = [
        ("display", labels.get("node.image_role_display", "Display")),
        ("map", labels.get("node.image_role_map", "Map")),
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
        form.hero_image_role.data = "display"
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
        form.hero_image_role.data = "display"

    if form.validate_on_submit():
        if node is None:
            node = GardenNode(parent=parent, level=level)
            db.session.add(node)
            db.session.flush()

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

        image_kind = "node_map" if form.hero_image_role.data == "map" else "node_display"
        uploaded_image = save_data_url_upload(
            form.processed_hero_image_data.data,
            f"node-{level}",
            image_kind=image_kind,
            subfolder=f"nodes/{node.id}",
        ) or save_uploaded_file(
            form.hero_image.data,
            f"node-{level}",
            image_kind=image_kind,
            subfolder=f"nodes/{node.id}",
        )
        if uploaded_image:
            if form.hero_image_role.data == "map":
                node.map_image_path = uploaded_image
            else:
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
        irrigation_zones=node.irrigation_zones if node is not None else [],
        delete_form=DeleteForm(),
    )


@bp.route("/nodes/<int:node_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_node(node_id: int):
    """Delete a node after delete-form confirmation.

    Parameters:
        node_id: Identifier of the node to remove.
    """
    node = GardenNode.query.get_or_404(node_id)
    parent_id = node.parent_id
    form = DeleteForm()
    if form.validate_on_submit():
        image_paths = _collect_node_image_paths(node) if form.remove_files.data else set()
        db.session.delete(node)
        db.session.commit()
        if image_paths:
            removed_count = remove_unreferenced_uploads(_upload_directory(), image_paths)
            if removed_count:
                flash(f"Removed {removed_count} uploaded file(s).", "success")
        flash("Node deleted.", "success")
    else:
        flash("Delete request was rejected.", "danger")

    if parent_id:
        return redirect(url_for("main.node_detail", node_id=parent_id))
    return redirect(url_for("main.index"))


@bp.route("/nodes/<int:node_id>/photos", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def add_photo(node_id: int):
    """Open the node photo import flow and save the confirmed image.

    Parameters:
        node_id: Identifier of the node receiving the imported image.
    """
    node = GardenNode.query.get_or_404(node_id)
    form = PhotoForm(prefix="photo")

    if form.validate_on_submit():
        image = form.image.data
        taken_at = extract_exif_taken_at(image) or datetime.now(UTC)
        image_path = save_data_url_upload(
            form.processed_image_data.data,
            f"photo-{node.id}",
            image_kind="node_photo",
            subfolder=f"nodes/{node.id}",
        ) or save_uploaded_file(
            image,
            f"photo-{node.id}",
            image_kind="node_photo",
            subfolder=f"nodes/{node.id}",
        )

        if not image_path:
            flash("Image could not be saved. Try again.", "danger")
            return render_template(
                "photo_import_form.html",
                form=form,
                node=node,
                settings=_settings(),
            )

        photo = NodePhoto(
            node=node,
            title=form.title.data.strip() if form.title.data else filename_stem(image.filename),
            caption=form.caption.data.strip() if form.caption.data else None,
            image_path=image_path,
            image_role=form.image_role.data,
            taken_at=taken_at,
            is_default=node.default_photo is None,
            sort_order=len(node.photos),
        )
        db.session.add(photo)
        db.session.commit()
        flash("Image imported.", "success")
        return redirect(url_for("main.node_detail", node_id=node.id))

    if request.method == "POST":
        flash("Image could not be added. Check the form fields.", "danger")

    return render_template(
        "photo_import_form.html",
        form=form,
        node=node,
        settings=_settings(),
    )


@bp.route("/nodes/<int:node_id>/activities", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def add_activity(node_id: int):
    """Create a new activity entry for a node.

    Parameters:
        node_id: Identifier of the node receiving the activity.
    """
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

        image = form.image.data
        image_path = save_data_url_upload(
            form.processed_image_data.data,
            f"activity-{activity.id}",
            image_kind="activity_image",
            subfolder=f"nodes/{node.id}",
        ) or save_uploaded_file(
            image,
            f"activity-{activity.id}",
            image_kind="activity_image",
            subfolder=f"nodes/{node.id}",
        )
        if image_path:
            db.session.add(
                NodeActivityImage(
                    activity=activity,
                    title=filename_stem(image.filename if image is not None else "activity-image"),
                    image_path=image_path,
                )
            )

        db.session.commit()
        flash("Activity added.", "success")
        return redirect(url_for("main.node_detail", node_id=node.id))
    if request.method == "POST":
        flash("Activity could not be added. Check the form fields.", "danger")

    return render_template(
        "activity_form.html",
        form=form,
        activity=None,
        node=node,
        settings=_settings(),
        delete_form=DeleteForm(),
    )


@bp.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_activity(activity_id: int):
    """Edit an existing node activity.

    Parameters:
        activity_id: Identifier of the activity to update.
    """
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

        image = form.image.data
        image_path = save_data_url_upload(
            form.processed_image_data.data,
            f"activity-{activity.id}",
            image_kind="activity_image",
            subfolder=f"nodes/{activity.node_id}",
        ) or save_uploaded_file(
            image,
            f"activity-{activity.id}",
            image_kind="activity_image",
            subfolder=f"nodes/{activity.node_id}",
        )
        if image_path:
            db.session.add(
                NodeActivityImage(
                    activity=activity,
                    title=filename_stem(image.filename if image is not None else "activity-image"),
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
    """Delete an activity from a node's history.

    Parameters:
        activity_id: Identifier of the activity to remove.
    """
    activity = NodeActivity.query.get_or_404(activity_id)
    node_id = activity.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        image_paths = _collect_activity_image_paths(activity) if form.remove_files.data else set()
        db.session.delete(activity)
        db.session.commit()
        if image_paths:
            removed_count = remove_unreferenced_uploads(_upload_directory(), image_paths)
            if removed_count:
                flash(f"Removed {removed_count} uploaded file(s).", "success")
        flash("Activity deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/photos/<int:photo_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_photo(photo_id: int):
    """Edit metadata for a node photo.

    Parameters:
        photo_id: Identifier of the photo to update.
    """
    photo = NodePhoto.query.get_or_404(photo_id)
    form = PhotoEditForm(obj=photo)

    if request.method == "GET":
        form.taken_at.data = photo.taken_at.date()
        form.is_default.data = photo.is_default
        form.image_role.data = photo.image_role or "gallery"

    if form.validate_on_submit():
        photo.title = form.title.data.strip()
        photo.image_role = form.image_role.data
        photo.caption = form.caption.data.strip() if form.caption.data else None
        photo.taken_at = datetime.combine(form.taken_at.data, datetime.min.time(), tzinfo=UTC)
        uploaded_image = save_data_url_upload(
            form.processed_image_data.data,
            f"photo-{photo.node_id}",
            image_kind="node_photo",
            subfolder=f"nodes/{photo.node_id}",
        ) or save_uploaded_file(
            form.image.data,
            f"photo-{photo.node_id}",
            image_kind="node_photo",
            subfolder=f"nodes/{photo.node_id}",
        )
        if uploaded_image:
            photo.image_path = uploaded_image
        if form.is_default.data:
            _set_default_photo(photo.node, photo)
        elif photo.is_default and any(candidate.id != photo.id for candidate in photo.node.photos):
            photo.is_default = False
        photo.sort_order = form.sort_order.data or 0
        db.session.commit()
        flash("Photo updated.", "success")
        return redirect(url_for("main.node_detail", node_id=photo.node_id))

    return render_template(
        "photo_form.html",
        form=form,
        photo=photo,
        node=photo.node,
        settings=_settings(),
    )


@bp.route("/nodes/<int:node_id>/images/<string:image_role>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_node_image(node_id: int, image_role: str):
    """Replace a legacy dedicated node image using the same preview editor as uploads.

    Parameters:
        node_id: Identifier of the node whose dedicated image should be replaced.
        image_role: Dedicated image role, either ``display`` or ``map``.
    """
    node = GardenNode.query.get_or_404(node_id)
    if image_role not in {"display", "map"}:
        flash("Unknown node image role.", "danger")
        return redirect(url_for("main.edit_node", node_id=node.id))

    current_path = _node_image_role_path(node, image_role)
    if not current_path:
        flash("No image is currently stored for that role.", "warning")
        return redirect(url_for("main.edit_node", node_id=node.id))

    form = NodeImageEditForm()
    if form.validate_on_submit():
        image_kind = "node_map" if image_role == "map" else "node_display"
        uploaded_image = save_data_url_upload(
            form.processed_image_data.data,
            f"node-{node.id}",
            image_kind=image_kind,
            subfolder=f"nodes/{node.id}",
        ) or save_uploaded_file(
            form.image.data,
            f"node-{node.id}",
            image_kind=image_kind,
            subfolder=f"nodes/{node.id}",
        )
        if not uploaded_image:
            flash("Image could not be saved. Try again.", "danger")
        else:
            if image_role == "map":
                node.map_image_path = uploaded_image
            else:
                node.hero_image_path = uploaded_image
            db.session.commit()
            flash("Image updated.", "success")
            return redirect(url_for("main.edit_node", node_id=node.id))

    return render_template(
        "node_image_edit_form.html",
        form=form,
        node=node,
        image_role=image_role,
        current_image_path=current_path,
        settings=_settings(),
    )


@bp.route("/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_photo(photo_id: int):
    """Delete a photo and promote a replacement default when needed.

    Parameters:
        photo_id: Identifier of the photo to remove.
    """
    photo = NodePhoto.query.get_or_404(photo_id)
    node_id = photo.node_id
    node = photo.node
    form = DeleteForm()
    if form.validate_on_submit():
        image_paths = {photo.image_path} if form.remove_files.data and photo.image_path else set()
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
        if image_paths:
            removed_count = remove_unreferenced_uploads(_upload_directory(), image_paths)
            if removed_count:
                flash(f"Removed {removed_count} uploaded file(s).", "success")
        flash("Photo deleted.", "success")
    return redirect(url_for("main.node_detail", node_id=node_id))


@bp.route("/nodes/<int:node_id>/links", methods=["POST"])
@login_required
@permission_required("manage_content")
def add_link(node_id: int):
    """Attach an external reference link to a node.

    Parameters:
        node_id: Identifier of the node receiving the link.
    """
    node = GardenNode.query.get_or_404(node_id)
    form = _external_link_form()

    if form.validate_on_submit():
        link_type = db.session.get(LinkType, form.link_type_id.data)
        if link_type is None:
            flash("Selected link type was not found.", "danger")
            return redirect(url_for("main.edit_node", node_id=node.id))
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
    """Delete an external link from a node.

    Parameters:
        link_id: Identifier of the link to remove.
    """
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
    """Edit an existing external link.

    Parameters:
        link_id: Identifier of the link to update.
    """
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


@bp.route("/nodes/<int:node_id>/entities", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def add_entity(node_id: int):
    """Link a Home Assistant entity to a node.

    Parameters:
        node_id: Identifier of the node receiving the entity link.
    """
    node = GardenNode.query.get_or_404(node_id)
    form = _home_assistant_entity_form()

    if request.method == "GET":
        current_image_path = node.map_view_image
        return render_template(
            "entity_form.html",
            form=form,
            entity=None,
            node=node,
            current_image_path=current_image_path,
            settings=_settings(),
        )

    if form.validate_on_submit():
        catalog_entry = db.session.get(HomeAssistantEntityCatalog, form.discovered_entity.data)
        if catalog_entry is None:
            flash("Selected Home Assistant entity was not found. Re-sync the catalog.", "danger")
            return redirect(url_for("main.edit_node", node_id=node.id))
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

    return redirect(url_for("main.edit_node", node_id=node.id))


@bp.route("/entities/<int:entity_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_entity(entity_id: int):
    """Delete a Home Assistant entity link from a node.

    Parameters:
        entity_id: Identifier of the linked entity record to remove.
    """
    entity = NodeHomeAssistantEntity.query.get_or_404(entity_id)
    node_id = entity.node_id
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(entity)
        db.session.commit()
        flash("Entity deleted.", "success")
    return redirect(url_for("main.edit_node", node_id=node_id))


@bp.route("/entities/<int:entity_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_entity(entity_id: int):
    """Edit a Home Assistant entity link.

    Parameters:
        entity_id: Identifier of the linked entity record to update.
    """
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
            return redirect(url_for("main.edit_node", node_id=entity.node_id))

        existing_link = NodeHomeAssistantEntity.query.filter(
            NodeHomeAssistantEntity.node_id == entity.node_id,
            NodeHomeAssistantEntity.entity_id == catalog_entry.entity_id,
            NodeHomeAssistantEntity.id != entity.id,
        ).first()
        if existing_link:
            flash("That Home Assistant entity is already linked to this node.", "warning")
            return redirect(url_for("main.edit_node", node_id=entity.node_id))

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
        return redirect(url_for("main.edit_node", node_id=entity.node_id))

    current_image_path = entity.node.map_view_image
    return render_template(
        "entity_form.html",
        form=form,
        entity=entity,
        node=entity.node,
        current_image_path=current_image_path,
        settings=_settings(),
    )


@bp.route("/nodes/<int:node_id>/irrigation-zones/new", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def add_irrigation_zone(node_id: int):
    """Create a new irrigation zone on a node image.

    Parameters:
        node_id: Identifier of the node receiving the irrigation zone.
    """
    node = GardenNode.query.get_or_404(node_id)
    return _upsert_irrigation_zone(node=node, zone=None)


@bp.route("/irrigation-zones/<int:zone_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_content")
def edit_irrigation_zone(zone_id: int):
    """Edit an existing irrigation zone.

    Parameters:
        zone_id: Identifier of the irrigation zone to update.
    """
    zone = NodeIrrigationZone.query.get_or_404(zone_id)
    return _upsert_irrigation_zone(node=zone.node, zone=zone)


@bp.route("/irrigation-zones/<int:zone_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_content")
def delete_irrigation_zone(zone_id: int):
    """Delete an irrigation zone from a node image.

    Parameters:
        zone_id: Identifier of the irrigation zone to remove.
    """
    zone = NodeIrrigationZone.query.get_or_404(zone_id)
    node_id = zone.node_id
    fallback_url = url_for("main.edit_node", node_id=node_id)
    form = DeleteForm()
    if form.validate_on_submit():
        db.session.delete(zone)
        db.session.commit()
        flash("Irrigation zone deleted.", "success")
    return redirect(request.referrer or fallback_url)


def _upsert_irrigation_zone(node: GardenNode, zone: NodeIrrigationZone | None):
    """Create or update an irrigation zone linked to a node image.

    Parameters:
        node: Node that owns the irrigation zone.
        zone: Existing irrigation zone being edited, or None when creating one.
    """
    if not node.map_view_image:
        flash("Add a map image to this node before placing irrigation zones.", "warning")
        return redirect(url_for("main.edit_node", node_id=node.id))

    form = _irrigation_zone_form(zone)
    if request.method == "GET" and zone is not None:
        catalog_entry = (
            HomeAssistantEntityCatalog.query.filter_by(entity_id=zone.entity_id).first()
            if zone.entity_id
            else None
        )
        if catalog_entry is not None:
            form.discovered_entity.data = catalog_entry.id
        form.name.data = zone.name
        form.overlay_color.data = zone.overlay_color_key
        form.texture_pattern.data = zone.texture_pattern_key
        form.subzone_rectangles_json.data = json.dumps(
            [{"points": [{"x": x, "y": y} for x, y in polygon]} for polygon in zone.subzone_polygons]
        )
        (
            form.area_corner_1_x.data,
            form.area_corner_1_y.data,
            form.area_corner_2_x.data,
            form.area_corner_2_y.data,
            form.area_corner_3_x.data,
            form.area_corner_3_y.data,
            form.area_corner_4_x.data,
            form.area_corner_4_y.data,
        ) = (
            zone.area_corner_1_x,
            zone.area_corner_1_y,
            zone.area_corner_2_x,
            zone.area_corner_2_y,
            zone.area_corner_3_x,
            zone.area_corner_3_y,
            zone.area_corner_4_x,
            zone.area_corner_4_y,
        )

    if form.validate_on_submit():
        catalog_entry = (
            db.session.get(HomeAssistantEntityCatalog, form.discovered_entity.data)
            if form.discovered_entity.data
            else None
        )
        if form.discovered_entity.data and catalog_entry is None:
            flash("Selected Home Assistant entity was not found. Re-sync the catalog.", "danger")
            return redirect(url_for("main.edit_node", node_id=node.id))

        polygon_points = _polygon_from_irrigation_form(form)
        subzone_polygons = _subzone_polygons_from_irrigation_form(form)
        if not polygon_points:
            flash("Draw the irrigation zone directly on the image before saving.", "danger")
            return render_template(
                "irrigation_zone_form.html",
                form=form,
                zone=zone,
                node=node,
                current_image_path=node.map_view_image,
                irrigation_zones=node.irrigation_zones,
                settings=_settings(),
                delete_form=DeleteForm(),
            )

        if zone is None:
            zone = NodeIrrigationZone(node=node)
            db.session.add(zone)

        zone.name = form.name.data.strip()
        zone.entity_id = catalog_entry.entity_id if catalog_entry is not None else None
        zone.current_value = catalog_entry.state if catalog_entry is not None else None
        zone.unit_of_measurement = (
            catalog_entry.unit_of_measurement if catalog_entry is not None else None
        )
        zone.last_synced_at = datetime.now(UTC) if catalog_entry is not None else None
        zone.overlay_width, zone.overlay_height = _polygon_bounds(polygon_points)
        zone.map_x, zone.map_y = _polygon_centroid(polygon_points)
        zone.overlay_color = form.overlay_color.data or DEFAULT_IRRIGATION_ZONE_COLOR
        zone.texture_pattern = form.texture_pattern.data or DEFAULT_IRRIGATION_ZONE_TEXTURE
        zone.subzone_rectangles_json = json.dumps(subzone_polygons)
        (
            zone.area_corner_1_x,
            zone.area_corner_1_y,
            zone.area_corner_2_x,
            zone.area_corner_2_y,
            zone.area_corner_3_x,
            zone.area_corner_3_y,
            zone.area_corner_4_x,
            zone.area_corner_4_y,
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

        db.session.commit()
        flash("Irrigation zone saved.", "success")
        return redirect(url_for("main.edit_node", node_id=node.id))

    return render_template(
        "irrigation_zone_form.html",
        form=form,
        zone=zone,
        node=node,
        current_image_path=node.map_view_image,
        irrigation_zones=node.irrigation_zones,
        settings=_settings(),
        delete_form=DeleteForm(),
    )


def _home_assistant_entity_form() -> HomeAssistantEntityForm:
    """Build the Home Assistant entity form with discovered catalog choices."""
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


def _irrigation_zone_form(zone: NodeIrrigationZone | None = None) -> IrrigationZoneForm:
    """Build the irrigation zone form with discovered Home Assistant entities.

    Parameters:
        zone: Existing irrigation zone being edited, if any.
    """
    form = IrrigationZoneForm(prefix="irrigation")
    labels = _localized_labels()
    catalog_entries = HomeAssistantEntityCatalog.query.order_by(
        HomeAssistantEntityCatalog.domain,
        HomeAssistantEntityCatalog.friendly_name,
        HomeAssistantEntityCatalog.entity_id,
    ).all()
    form.overlay_color.choices = [
        (color_key, labels.get(f"node.irrigation_color_{color_key}", color_key.title()))
        for color_key in IRRIGATION_ZONE_COLORS
    ]
    form.texture_pattern.choices = [
        (texture_key, labels.get(f"node.irrigation_texture_{texture_key}", texture_key.title()))
        for texture_key in IRRIGATION_ZONE_TEXTURES
    ]
    form.discovered_entity.choices = [(0, labels.get("node.entity_none", "No Home Assistant entity"))] + [
        (
            entry.id,
            _entity_choice_label(entry),
        )
        for entry in catalog_entries
    ]
    if request.method == "GET":
        form.map_x.data = zone.map_x if zone is not None and zone.map_x is not None else 50
        form.map_y.data = zone.map_y if zone is not None and zone.map_y is not None else 50
        form.overlay_width.data = (
            zone.overlay_width
            if zone is not None and zone.overlay_width is not None
            else 18
        )
        form.overlay_height.data = (
            zone.overlay_height
            if zone is not None and zone.overlay_height is not None
            else 12
        )
        form.overlay_color.data = (
            zone.overlay_color_key if zone is not None else DEFAULT_IRRIGATION_ZONE_COLOR
        )
        form.texture_pattern.data = (
            zone.texture_pattern_key if zone is not None else DEFAULT_IRRIGATION_ZONE_TEXTURE
        )
        form.subzone_rectangles_json.data = (
            json.dumps(
                [{"points": [{"x": x, "y": y} for x, y in polygon]} for polygon in zone.subzone_polygons]
            )
            if zone is not None
            else "[]"
        )
    return form


def _activity_form(activity: NodeActivity | None = None) -> NodeActivityForm:
    """Build the activity form with the current activity type choices.

    Parameters:
        activity: Existing activity being edited, if any.
    """
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
    """Build the external-link form with localized link type choices."""
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
    """Format one Home Assistant catalog entry for a dropdown option.

    Parameters:
        entry: Catalog entry to represent in the select field.
    """
    name = entry.friendly_name or entry.entity_id
    state = entry.state or "unknown"
    unit = f" {entry.unit_of_measurement}" if entry.unit_of_measurement else ""
    return f"{name} [{entry.entity_id}] - {state}{unit}"
