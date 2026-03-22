from __future__ import annotations

from datetime import datetime, UTC

from flask import has_request_context
from flask_login import UserMixin
from flask_login import current_user
from sqlalchemy.exc import OperationalError
from sqlalchemy import UniqueConstraint, event, inspect, text
from sqlalchemy.orm import Session

from .extensions import db
from .translations import DEFAULT_LOCALE, DEFAULT_TRANSLATIONS


DEFAULT_MARKER_COLORS = [
    ("Orange", "#f28c28"),
    ("Red", "#d64545"),
    ("Blue", "#2f6fed"),
    ("Green", "#3e8b53"),
    ("Yellow", "#e3b505"),
    ("Purple", "#7b5fd6"),
    ("Pink", "#d95d8f"),
    ("Teal", "#1f9d8b"),
    ("Cyan", "#22b8cf"),
    ("Brown", "#8a5a44"),
    ("Olive", "#708238"),
    ("Lime", "#8ccf47"),
    ("Indigo", "#4b5bdc"),
    ("Violet", "#985eff"),
    ("Slate", "#5f6b7a"),
    ("Black", "#1f1f1f"),
]

DEFAULT_MARKER_COLOR_BY_NODE_TYPE = {
    "plant": 0,
    "bed": 1,
    "section": 2,
}


def _clamp_percent(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False)


class AuditMixin:
    created_by_name = db.Column(db.String(80), nullable=True)
    updated_by_name = db.Column(db.String(80), nullable=True)


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    is_system = db.Column(db.Boolean, default=True, nullable=False)
    permissions = db.relationship(
        "Permission",
        secondary=role_permissions,
        lazy="joined",
        backref=db.backref("roles", lazy="dynamic"),
    )


class User(UserMixin, AuditMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    preferred_locale = db.Column(db.String(8), nullable=False, default=DEFAULT_LOCALE)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    roles = db.relationship(
        "Role",
        secondary=user_roles,
        lazy="joined",
        backref=db.backref("users", lazy="dynamic"),
    )
    login_history = db.relationship(
        "UserLoginHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by=lambda: db.desc(UserLoginHistory.logged_in_at),
    )

    def set_password(self, password: str) -> None:
        from werkzeug.security import generate_password_hash

        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash

        return check_password_hash(self.password_hash, password)

    def has_permission(self, permission_code: str) -> bool:
        return any(
            permission.code == permission_code
            for role in self.roles
            for permission in role.permissions
        )

    def role_names(self) -> list[str]:
        return sorted(role.name for role in self.roles)


class GardenSettings(AuditMixin, db.Model):
    __tablename__ = "garden_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    site_name = db.Column(db.String(120), nullable=False, default="Piantala")
    welcome_text = db.Column(
        db.Text,
        nullable=False,
        default="Map-based garden management for areas, beds, and plants.",
    )
    map_provider = db.Column(db.String(32), nullable=False, default="image")
    color_scheme = db.Column(db.String(32), nullable=False, default="earth")
    font_family = db.Column(db.String(32), nullable=False, default="classic_serif")
    default_locale = db.Column(db.String(8), nullable=False, default=DEFAULT_LOCALE)
    map_image_path = db.Column(db.String(255), nullable=True)
    google_maps_center_lat = db.Column(db.Float, nullable=True)
    google_maps_center_lng = db.Column(db.Float, nullable=True)
    google_maps_zoom = db.Column(db.Integer, nullable=False, default=19)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @classmethod
    def get_or_create(cls) -> "GardenSettings":
        settings = cls.query.first()
        if settings is None:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings


class MarkerColor(AuditMixin, db.Model):
    __tablename__ = "marker_colors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    hex_value = db.Column(db.String(16), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    nodes = db.relationship(
        "GardenNode",
        back_populates="marker_color",
        order_by="GardenNode.title",
    )


class GardenNode(AuditMixin, db.Model):
    __tablename__ = "garden_nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "title", name="uq_node_parent_title"),
    )

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("garden_nodes.id"), nullable=True)
    level = db.Column(db.Integer, nullable=False)
    node_type = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    life_cycle = db.Column(db.String(16), nullable=True)
    planting_date = db.Column(db.Date, nullable=True)
    death_year = db.Column(db.Integer, nullable=True)
    hero_image_path = db.Column(db.String(255), nullable=True)
    image_display_mode = db.Column(db.String(16), nullable=False, default="contain")
    image_focus_x = db.Column(db.Float, nullable=False, default=50.0)
    image_focus_y = db.Column(db.Float, nullable=False, default=50.0)
    map_x = db.Column(db.Float, nullable=True)
    map_y = db.Column(db.Float, nullable=True)
    overlay_shape = db.Column(db.String(16), nullable=False, default="point")
    overlay_width = db.Column(db.Float, nullable=False, default=18.0)
    overlay_height = db.Column(db.Float, nullable=False, default=12.0)
    area_corner_1_x = db.Column(db.Float, nullable=True)
    area_corner_1_y = db.Column(db.Float, nullable=True)
    area_corner_2_x = db.Column(db.Float, nullable=True)
    area_corner_2_y = db.Column(db.Float, nullable=True)
    area_corner_3_x = db.Column(db.Float, nullable=True)
    area_corner_3_y = db.Column(db.Float, nullable=True)
    area_corner_4_x = db.Column(db.Float, nullable=True)
    area_corner_4_y = db.Column(db.Float, nullable=True)
    marker_color_id = db.Column(db.Integer, db.ForeignKey("marker_colors.id"), nullable=True)
    hotspot_color = db.Column(db.String(16), nullable=False, default="#2f6f4f")
    marker_icon = db.Column(db.String(64), nullable=True)
    geo_lat = db.Column(db.Float, nullable=True)
    geo_lng = db.Column(db.Float, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    parent = db.relationship(
        "GardenNode",
        remote_side=[id],
        back_populates="children",
    )
    marker_color = db.relationship("MarkerColor", back_populates="nodes")
    children = db.relationship(
        "GardenNode",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="GardenNode.sort_order, GardenNode.title",
    )
    photos = db.relationship(
        "NodePhoto",
        back_populates="node",
        cascade="all, delete-orphan",
        order_by="NodePhoto.sort_order, NodePhoto.id",
    )
    activities = db.relationship(
        "NodeActivity",
        back_populates="node",
        cascade="all, delete-orphan",
        order_by=lambda: (db.desc(NodeActivity.happened_on), db.desc(NodeActivity.id)),
    )
    external_links = db.relationship(
        "NodeExternalLink",
        back_populates="node",
        cascade="all, delete-orphan",
        order_by="NodeExternalLink.link_type_id, NodeExternalLink.label",
    )
    ha_entities = db.relationship(
        "NodeHomeAssistantEntity",
        back_populates="node",
        cascade="all, delete-orphan",
        order_by="NodeHomeAssistantEntity.label",
    )

    LEVEL_LABELS = {
        1: "Area",
        2: "Section",
        3: "Bed",
        4: "Plant",
    }

    def can_have_children(self) -> bool:
        return self.level < 4

    @property
    def level_label(self) -> str:
        return self.LEVEL_LABELS.get(self.level, f"Level {self.level}")

    @property
    def display_image(self) -> str | None:
        if self.hero_image_path:
            return self.hero_image_path
        if self.latest_photo:
            return self.latest_photo.image_path
        return None

    @property
    def image_display_style(self) -> str:
        mode = self.image_display_mode or "contain"
        focus_x = self.image_focus_x if self.image_focus_x is not None else 50
        focus_y = self.image_focus_y if self.image_focus_y is not None else 50
        return (
            f"--image-fit: {mode}; "
            f"--image-position: {focus_x}% {focus_y}%;"
        )

    @property
    def latest_photo(self) -> "NodePhoto | None":
        if not self.photos:
            return None
        return sorted(
            self.photos,
            key=lambda photo: (photo.taken_at, photo.id),
            reverse=True,
        )[0]

    def breadcrumbs(self) -> list["GardenNode"]:
        current = self
        trail: list[GardenNode] = []
        while current is not None:
            trail.append(current)
            current = current.parent
        return list(reversed(trail))

    @property
    def has_hotspot(self) -> bool:
        return self.map_x is not None and self.map_y is not None

    @property
    def has_geo_point(self) -> bool:
        return self.geo_lat is not None and self.geo_lng is not None

    @property
    def marker_color_value(self) -> str:
        if self.marker_color is not None and self.marker_color.hex_value:
            return self.marker_color.hex_value
        if self.hotspot_color:
            return self.hotspot_color
        return "#f28c28"

    @property
    def marker_icon_class(self) -> str | None:
        icon = (self.marker_icon or "").strip()
        if not icon:
            return None
        return icon

    @property
    def area_polygon_points(self) -> list[tuple[float, float]]:
        stored_points = [
            (self.area_corner_1_x, self.area_corner_1_y),
            (self.area_corner_2_x, self.area_corner_2_y),
            (self.area_corner_3_x, self.area_corner_3_y),
            (self.area_corner_4_x, self.area_corner_4_y),
        ]
        if all(x is not None and y is not None for x, y in stored_points):
            return [(float(x), float(y)) for x, y in stored_points]

        if self.map_x is None or self.map_y is None:
            return []

        half_width = (self.overlay_width or 18.0) / 2
        half_height = (self.overlay_height or 12.0) / 2
        return [
            (_clamp_percent(self.map_x - half_width), _clamp_percent(self.map_y - half_height)),
            (_clamp_percent(self.map_x + half_width), _clamp_percent(self.map_y - half_height)),
            (_clamp_percent(self.map_x + half_width), _clamp_percent(self.map_y + half_height)),
            (_clamp_percent(self.map_x - half_width), _clamp_percent(self.map_y + half_height)),
        ]

    @property
    def area_overlay_style(self) -> str:
        points = self.area_polygon_points
        if len(points) != 4:
            return ""

        xs = [x for x, _y in points]
        ys = [y for _x, y in points]
        min_x = _clamp_percent(min(xs))
        max_x = _clamp_percent(max(xs))
        min_y = _clamp_percent(min(ys))
        max_y = _clamp_percent(max(ys))
        width = max(max_x - min_x, 0.5)
        height = max(max_y - min_y, 0.5)
        relative_points = ", ".join(
            f"{((x - min_x) / width) * 100:.2f}% {((y - min_y) / height) * 100:.2f}%"
            for x, y in points
        )
        centroid_x = sum(xs) / len(xs)
        centroid_y = sum(ys) / len(ys)
        tooltip_left = ((centroid_x - min_x) / width) * 100
        tooltip_top = ((centroid_y - min_y) / height) * 100
        return (
            f"left: {min_x:.2f}%; "
            f"top: {min_y:.2f}%; "
            f"width: {width:.2f}%; "
            f"height: {height:.2f}%; "
            f"--tooltip-left: {tooltip_left:.2f}%; "
            f"--tooltip-top: {tooltip_top:.2f}%; "
            f"--hotspot-color: {self.marker_color_value};"
        )

    @property
    def area_overlay_svg_points(self) -> str:
        points = self.area_polygon_points
        if len(points) != 4:
            return ""

        xs = [x for x, _y in points]
        ys = [y for _x, y in points]
        min_x = _clamp_percent(min(xs))
        max_x = _clamp_percent(max(xs))
        min_y = _clamp_percent(min(ys))
        max_y = _clamp_percent(max(ys))
        width = max(max_x - min_x, 0.5)
        height = max(max_y - min_y, 0.5)
        return " ".join(
            f"{((x - min_x) / width) * 100:.2f},{((y - min_y) / height) * 100:.2f}"
            for x, y in points
        )

    @property
    def is_dead(self) -> bool:
        return self.death_year is not None


class NodePhoto(AuditMixin, db.Model):
    __tablename__ = "node_photos"

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey("garden_nodes.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    caption = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(255), nullable=False)
    taken_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    node = db.relationship("GardenNode", back_populates="photos")


class ActivityType(AuditMixin, db.Model):
    __tablename__ = "activity_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    activities = db.relationship(
        "NodeActivity",
        back_populates="activity_type",
        order_by=lambda: (db.desc(NodeActivity.happened_on), db.desc(NodeActivity.id)),
    )


class NodeActivity(AuditMixin, db.Model):
    __tablename__ = "node_activities"

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey("garden_nodes.id"), nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_types.id"), nullable=False)
    happened_on = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    node = db.relationship("GardenNode", back_populates="activities")
    activity_type = db.relationship("ActivityType", back_populates="activities")
    images = db.relationship(
        "NodeActivityImage",
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="NodeActivityImage.id",
    )


class NodeActivityImage(AuditMixin, db.Model):
    __tablename__ = "node_activity_images"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("node_activities.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    activity = db.relationship("NodeActivity", back_populates="images")


class LinkType(AuditMixin, db.Model):
    __tablename__ = "link_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    requires_label = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    links = db.relationship(
        "NodeExternalLink",
        back_populates="link_type",
        order_by="NodeExternalLink.label",
    )

    @property
    def translation_key(self) -> str:
        return f"link_type.{self.id}.name"

    def localized_name(self, locale: str | None = None) -> str:
        if self.id is None:
            return self.name

        selected_locale = locale or DEFAULT_LOCALE
        entry = TranslationEntry.query.filter_by(
            locale=selected_locale,
            key=self.translation_key,
        ).first()
        if entry is not None and entry.text:
            return entry.text

        fallback_entry = TranslationEntry.query.filter_by(
            locale=DEFAULT_LOCALE,
            key=self.translation_key,
        ).first()
        if fallback_entry is not None and fallback_entry.text:
            return fallback_entry.text

        return self.name

    def save_localized_names(self, names_by_locale: dict[str, str], *, overwrite: bool = True) -> None:
        if self.id is None:
            raise ValueError("LinkType must be flushed before saving translations.")

        for locale, value in names_by_locale.items():
            cleaned_value = value.strip()
            if not cleaned_value:
                continue

            entry = TranslationEntry.query.filter_by(
                locale=locale,
                key=self.translation_key,
            ).first()
            if entry is None:
                db.session.add(
                    TranslationEntry(
                        locale=locale,
                        key=self.translation_key,
                        text=cleaned_value,
                    )
                )
            elif overwrite:
                entry.text = cleaned_value


class NodeExternalLink(AuditMixin, db.Model):
    __tablename__ = "node_external_links"

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey("garden_nodes.id"), nullable=False)
    link_type_id = db.Column(db.Integer, db.ForeignKey("link_types.id"), nullable=True)
    label = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)

    node = db.relationship("GardenNode", back_populates="external_links")
    link_type = db.relationship("LinkType", back_populates="links")

    def display_label(self, locale: str | None = None) -> str:
        cleaned_label = (self.label or "").strip()
        if cleaned_label:
            return cleaned_label
        if self.link_type is not None:
            return self.link_type.localized_name(locale)
        return self.url


class NodeHomeAssistantEntity(AuditMixin, db.Model):
    __tablename__ = "node_home_assistant_entities"

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey("garden_nodes.id"), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(255), nullable=False)
    current_value = db.Column(db.String(120), nullable=True)
    unit_of_measurement = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    show_on_image = db.Column(db.Boolean, nullable=False, default=False)
    map_x = db.Column(db.Float, nullable=True)
    map_y = db.Column(db.Float, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    node = db.relationship("GardenNode", back_populates="ha_entities")


class HomeAssistantSettings(AuditMixin, db.Model):
    __tablename__ = "home_assistant_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    base_url = db.Column(db.String(255), nullable=True)
    internal_url = db.Column(db.String(255), nullable=True)
    access_token = db.Column(db.String(255), nullable=True)
    user_agent = db.Column(
        db.String(255),
        nullable=False,
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 Piantala/0.1"
        ),
    )
    verify_ssl = db.Column(db.Boolean, nullable=False, default=True)
    request_timeout = db.Column(db.Integer, nullable=False, default=10)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @classmethod
    def get_or_create(cls) -> "HomeAssistantSettings":
        settings = cls.query.first()
        if settings is None:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings

    @property
    def is_configured(self) -> bool:
        return bool((self.internal_url or self.base_url) and self.access_token)

    @property
    def effective_url(self) -> str | None:
        return self.internal_url or self.base_url


class HomeAssistantEntityCatalog(AuditMixin, db.Model):
    __tablename__ = "home_assistant_entity_catalog"

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.String(255), unique=True, nullable=False)
    domain = db.Column(db.String(64), nullable=False)
    friendly_name = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(255), nullable=True)
    unit_of_measurement = db.Column(db.String(64), nullable=True)
    icon = db.Column(db.String(128), nullable=True)
    device_class = db.Column(db.String(128), nullable=True)
    last_updated = db.Column(db.String(64), nullable=True)
    raw_attributes_json = db.Column(db.Text, nullable=True)
    seen_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)


class TranslationEntry(AuditMixin, db.Model):
    __tablename__ = "translation_entries"
    __table_args__ = (
        UniqueConstraint("locale", "key", name="uq_translation_locale_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    locale = db.Column(db.String(8), nullable=False)
    key = db.Column(db.String(128), nullable=False)
    text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UserLoginHistory(db.Model):
    __tablename__ = "user_login_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    logged_in_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    user = db.relationship("User", back_populates="login_history")


def _audit_actor_name() -> str:
    try:
        if has_request_context() and getattr(current_user, "is_authenticated", False):
            username = (current_user.username or "").strip()
            if username:
                return username
    except Exception:
        pass
    return "System"


@event.listens_for(Session, "before_flush")
def _stamp_audit_fields(session, flush_context, instances) -> None:
    actor_name = _audit_actor_name()

    for obj in session.new:
        if isinstance(obj, AuditMixin):
            if not obj.created_by_name:
                obj.created_by_name = actor_name
            obj.updated_by_name = actor_name

    for obj in session.dirty:
        if isinstance(obj, AuditMixin) and session.is_modified(obj, include_collections=True):
            obj.updated_by_name = actor_name


def ensure_seed_data() -> None:
    permissions_map = {
        "view_dashboard": "Can view the garden dashboard and node pages.",
        "manage_content": "Can create and edit garden content.",
        "manage_users": "Can manage users and roles.",
    }

    permissions_by_code: dict[str, Permission] = {}
    for code, description in permissions_map.items():
        permission = Permission.query.filter_by(code=code).first()
        if permission is None:
            permission = Permission(code=code, description=description)
            db.session.add(permission)
        permissions_by_code[code] = permission

    db.session.flush()

    role_map = {
        "admin": {
            "description": "Full access to Piantala.",
            "permissions": ["view_dashboard", "manage_content", "manage_users"],
        },
        "editor": {
            "description": "Can manage map content, areas, and plants.",
            "permissions": ["view_dashboard", "manage_content"],
        },
        "viewer": {
            "description": "Read-only access to the garden.",
            "permissions": ["view_dashboard"],
        },
    }

    for role_name, payload in role_map.items():
        role = Role.query.filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name, description=payload["description"], is_system=True)
            db.session.add(role)
        else:
            role.description = payload["description"]
        role.permissions = [permissions_by_code[code] for code in payload["permissions"]]

    db.session.flush()

    if GardenSettings.query.first() is None:
        db.session.add(GardenSettings())
    if HomeAssistantSettings.query.first() is None:
        db.session.add(HomeAssistantSettings())

    marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()
    if not marker_colors:
        for index, (name, hex_value) in enumerate(DEFAULT_MARKER_COLORS):
            db.session.add(
                MarkerColor(
                    name=name,
                    hex_value=hex_value,
                    sort_order=index,
                )
            )
        db.session.flush()
        marker_colors = MarkerColor.query.order_by(MarkerColor.sort_order, MarkerColor.id).all()

    default_activity_types = [
        ("Fertilization", "Fertilizer application and soil enrichment."),
        ("Plowing", "Soil preparation, plowing, or tilling work."),
        ("Disinfestation", "Pest treatment, disease treatment, or disinfestation."),
    ]
    for index, (name, description) in enumerate(default_activity_types):
        activity_type = ActivityType.query.filter_by(name=name).first()
        if activity_type is None:
            db.session.add(
                ActivityType(
                    name=name,
                    description=description,
                    sort_order=index,
                )
            )

    default_link_types = [
        (
            {"en": "Provenance", "it": "Provenienza"},
            "Where the plant, seed, or material was bought or sourced.",
        ),
        (
            {"en": "Species", "it": "Specie"},
            "Reference page for species, cultivar, or taxonomy.",
        ),
    ]
    for index, (names_by_locale, description) in enumerate(default_link_types):
        canonical_name = names_by_locale[DEFAULT_LOCALE]
        link_type = LinkType.query.filter_by(name=canonical_name).first()
        if link_type is None:
            link_type = LinkType(
                name=canonical_name,
                description=description,
                sort_order=index,
            )
            db.session.add(link_type)
            db.session.flush()
        elif link_type.description is None:
            link_type.description = description
        if link_type.id is not None:
            link_type.save_localized_names(names_by_locale, overwrite=False)

    for key, localized_values in DEFAULT_TRANSLATIONS.items():
        for locale, text_value in localized_values.items():
            entry = TranslationEntry.query.filter_by(locale=locale, key=key).first()
            if entry is None:
                db.session.add(TranslationEntry(locale=locale, key=key, text=text_value))

    marker_colors_by_sort = {
        marker_color.sort_order: marker_color
        for marker_color in marker_colors
    }
    default_marker_colors_by_type = {
        node_type: marker_colors_by_sort.get(sort_order)
        for node_type, sort_order in DEFAULT_MARKER_COLOR_BY_NODE_TYPE.items()
    }

    for node in GardenNode.query.all():
        default_marker_color = default_marker_colors_by_type.get(node.node_type)
        if node.marker_color_id is None and default_marker_color is not None:
            node.marker_color = default_marker_color
        if node.marker_color is not None:
            node.hotspot_color = node.marker_color.hex_value

    db.session.commit()


def sync_schema() -> None:
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    statements = {
        "users": {
            "preferred_locale": (
                "ALTER TABLE users "
                f"ADD COLUMN preferred_locale VARCHAR(8) NOT NULL DEFAULT '{DEFAULT_LOCALE}'"
            ),
            "last_login_at": (
                "ALTER TABLE users "
                "ADD COLUMN last_login_at DATETIME"
            ),
            "created_by_name": (
                "ALTER TABLE users "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE users "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "garden_settings": {
            "created_by_name": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "map_provider": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN map_provider VARCHAR(32) NOT NULL DEFAULT 'image'"
            ),
            "color_scheme": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN color_scheme VARCHAR(32) NOT NULL DEFAULT 'earth'"
            ),
            "font_family": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN font_family VARCHAR(32) NOT NULL DEFAULT 'classic_serif'"
            ),
            "default_locale": (
                "ALTER TABLE garden_settings "
                f"ADD COLUMN default_locale VARCHAR(8) NOT NULL DEFAULT '{DEFAULT_LOCALE}'"
            ),
            "google_maps_center_lat": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN google_maps_center_lat FLOAT"
            ),
            "google_maps_center_lng": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN google_maps_center_lng FLOAT"
            ),
            "google_maps_zoom": (
                "ALTER TABLE garden_settings "
                "ADD COLUMN google_maps_zoom INTEGER NOT NULL DEFAULT 19"
            ),
        },
        "marker_colors": {
            "created_by_name": (
                "ALTER TABLE marker_colors "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE marker_colors "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "home_assistant_settings": {
            "created_by_name": (
                "ALTER TABLE home_assistant_settings "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE home_assistant_settings "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "internal_url": (
                "ALTER TABLE home_assistant_settings "
                "ADD COLUMN internal_url VARCHAR(255)"
            ),
            "user_agent": (
                "ALTER TABLE home_assistant_settings "
                "ADD COLUMN user_agent VARCHAR(255) NOT NULL DEFAULT "
                "'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Piantala/0.1'"
            ),
        },
        "activity_types": {
            "created_by_name": (
                "ALTER TABLE activity_types "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE activity_types "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "node_activities": {
            "created_by_name": (
                "ALTER TABLE node_activities "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE node_activities "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "node_activity_images": {
            "created_by_name": (
                "ALTER TABLE node_activity_images "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE node_activity_images "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "garden_nodes": {
            "created_by_name": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "quantity": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1"
            ),
            "life_cycle": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN life_cycle VARCHAR(16)"
            ),
            "planting_date": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN planting_date DATE"
            ),
            "death_year": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN death_year INTEGER"
            ),
            "image_display_mode": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN image_display_mode VARCHAR(16) NOT NULL DEFAULT 'contain'"
            ),
            "image_focus_x": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN image_focus_x FLOAT NOT NULL DEFAULT 50"
            ),
            "image_focus_y": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN image_focus_y FLOAT NOT NULL DEFAULT 50"
            ),
            "overlay_shape": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN overlay_shape VARCHAR(16) NOT NULL DEFAULT 'point'"
            ),
            "overlay_width": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN overlay_width FLOAT NOT NULL DEFAULT 18"
            ),
            "overlay_height": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN overlay_height FLOAT NOT NULL DEFAULT 12"
            ),
            "area_corner_1_x": "ALTER TABLE garden_nodes ADD COLUMN area_corner_1_x FLOAT",
            "area_corner_1_y": "ALTER TABLE garden_nodes ADD COLUMN area_corner_1_y FLOAT",
            "area_corner_2_x": "ALTER TABLE garden_nodes ADD COLUMN area_corner_2_x FLOAT",
            "area_corner_2_y": "ALTER TABLE garden_nodes ADD COLUMN area_corner_2_y FLOAT",
            "area_corner_3_x": "ALTER TABLE garden_nodes ADD COLUMN area_corner_3_x FLOAT",
            "area_corner_3_y": "ALTER TABLE garden_nodes ADD COLUMN area_corner_3_y FLOAT",
            "area_corner_4_x": "ALTER TABLE garden_nodes ADD COLUMN area_corner_4_x FLOAT",
            "area_corner_4_y": "ALTER TABLE garden_nodes ADD COLUMN area_corner_4_y FLOAT",
            "hotspot_color": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN hotspot_color VARCHAR(16) NOT NULL DEFAULT '#2f6f4f'"
            ),
            "marker_color_id": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN marker_color_id INTEGER"
            ),
            "marker_icon": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN marker_icon VARCHAR(64)"
            ),
            "geo_lat": "ALTER TABLE garden_nodes ADD COLUMN geo_lat FLOAT",
            "geo_lng": "ALTER TABLE garden_nodes ADD COLUMN geo_lng FLOAT",
        },
        "node_photos": {
            "created_by_name": (
                "ALTER TABLE node_photos "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE node_photos "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "taken_at": (
                "ALTER TABLE node_photos "
                "ADD COLUMN taken_at DATETIME"
            ),
        },
        "node_home_assistant_entities": {
            "created_by_name": (
                "ALTER TABLE node_home_assistant_entities "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE node_home_assistant_entities "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "show_on_image": (
                "ALTER TABLE node_home_assistant_entities "
                "ADD COLUMN show_on_image BOOLEAN NOT NULL DEFAULT 0"
            ),
            "map_x": "ALTER TABLE node_home_assistant_entities ADD COLUMN map_x FLOAT",
            "map_y": "ALTER TABLE node_home_assistant_entities ADD COLUMN map_y FLOAT",
        },
        "link_types": {
            "created_by_name": (
                "ALTER TABLE link_types "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE link_types "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "requires_label": (
                "ALTER TABLE link_types "
                "ADD COLUMN requires_label BOOLEAN NOT NULL DEFAULT 0"
            ),
        },
        "node_external_links": {
            "created_by_name": (
                "ALTER TABLE node_external_links "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE node_external_links "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
            "link_type_id": (
                "ALTER TABLE node_external_links "
                "ADD COLUMN link_type_id INTEGER"
            ),
        },
        "home_assistant_entity_catalog": {
            "created_by_name": (
                "ALTER TABLE home_assistant_entity_catalog "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE home_assistant_entity_catalog "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
        "translation_entries": {
            "created_by_name": (
                "ALTER TABLE translation_entries "
                "ADD COLUMN created_by_name VARCHAR(80)"
            ),
            "updated_by_name": (
                "ALTER TABLE translation_entries "
                "ADD COLUMN updated_by_name VARCHAR(80)"
            ),
        },
    }

    connection = db.session.connection()
    for table_name, columns in statements.items():
        if table_name not in existing_tables:
            continue

        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns.items():
            if column_name not in existing_columns:
                try:
                    connection.execute(text(ddl))
                    existing_columns.add(column_name)
                except OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise

    if "node_photos" in existing_tables:
        connection.execute(
            text(
                "UPDATE node_photos "
                "SET taken_at = COALESCE(taken_at, created_at)"
            )
        )

    db.session.commit()
