from __future__ import annotations

from datetime import datetime, UTC

from flask_login import UserMixin
from sqlalchemy.exc import OperationalError
from sqlalchemy import UniqueConstraint, inspect, text

from .extensions import db
from .translations import DEFAULT_LOCALE, DEFAULT_TRANSLATIONS


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


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)
    roles = db.relationship(
        "Role",
        secondary=user_roles,
        lazy="joined",
        backref=db.backref("users", lazy="dynamic"),
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


class GardenSettings(db.Model):
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


class GardenNode(db.Model):
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
    hotspot_color = db.Column(db.String(16), nullable=False, default="#2f6f4f")
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
    def is_dead(self) -> bool:
        return self.death_year is not None


class NodePhoto(db.Model):
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


class ActivityType(db.Model):
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


class NodeActivity(db.Model):
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


class NodeActivityImage(db.Model):
    __tablename__ = "node_activity_images"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("node_activities.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC), nullable=False)

    activity = db.relationship("NodeActivity", back_populates="images")


class LinkType(db.Model):
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


class NodeExternalLink(db.Model):
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


class NodeHomeAssistantEntity(db.Model):
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


class HomeAssistantSettings(db.Model):
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


class HomeAssistantEntityCatalog(db.Model):
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


class TranslationEntry(db.Model):
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

    db.session.commit()


def sync_schema() -> None:
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    statements = {
        "garden_settings": {
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
        "home_assistant_settings": {
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
        "garden_nodes": {
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
            "hotspot_color": (
                "ALTER TABLE garden_nodes "
                "ADD COLUMN hotspot_color VARCHAR(16) NOT NULL DEFAULT '#2f6f4f'"
            ),
            "geo_lat": "ALTER TABLE garden_nodes ADD COLUMN geo_lat FLOAT",
            "geo_lng": "ALTER TABLE garden_nodes ADD COLUMN geo_lng FLOAT",
        },
        "node_photos": {
            "taken_at": (
                "ALTER TABLE node_photos "
                "ADD COLUMN taken_at DATETIME"
            ),
        },
        "node_home_assistant_entities": {
            "show_on_image": (
                "ALTER TABLE node_home_assistant_entities "
                "ADD COLUMN show_on_image BOOLEAN NOT NULL DEFAULT 0"
            ),
            "map_x": "ALTER TABLE node_home_assistant_entities ADD COLUMN map_x FLOAT",
            "map_y": "ALTER TABLE node_home_assistant_entities ADD COLUMN map_y FLOAT",
        },
        "link_types": {
            "requires_label": (
                "ALTER TABLE link_types "
                "ADD COLUMN requires_label BOOLEAN NOT NULL DEFAULT 0"
            ),
        },
        "node_external_links": {
            "link_type_id": (
                "ALTER TABLE node_external_links "
                "ADD COLUMN link_type_id INTEGER"
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
