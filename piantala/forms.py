from __future__ import annotations

from urllib.parse import urlparse

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, MultipleFileField
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, URL, ValidationError

from .models import DEFAULT_IRRIGATION_ZONE_COLOR, DEFAULT_IRRIGATION_ZONE_TEXTURE, User
from .translations import SUPPORTED_LOCALES


IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"]
PHOTO_ROLE_CHOICES = [
    ("prospect", "Prospect"),
    ("map", "Map"),
    ("gallery", "Gallery"),
]


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")
    submit = SubmitField("Log in")


class MapSettingsForm(FlaskForm):
    site_name = StringField("Site name", validators=[DataRequired(), Length(max=120)])
    welcome_text = TextAreaField("Welcome text", validators=[DataRequired(), Length(max=1000)])
    color_scheme = SelectField(
        "Color scheme",
        choices=[
            ("earth", "Earth"),
            ("sage", "Sage"),
            ("terracotta", "Terracotta"),
            ("slate", "Slate"),
        ],
        validators=[DataRequired()],
    )
    font_family = SelectField(
        "Font family",
        choices=[
            ("classic_serif", "Classic serif"),
            ("clean_sans", "Clean sans"),
            ("humanist", "Humanist"),
            ("technical", "Technical"),
        ],
        validators=[DataRequired()],
    )
    map_provider = SelectField(
        "Homepage map provider",
        choices=[
            ("image", "Image map"),
            ("google", "Google Maps"),
            ("openstreetmap", "OpenStreetMap"),
            ("opentopomap", "OpenTopoMap"),
        ],
        validators=[DataRequired()],
    )
    map_image = FileField(
        "Map image",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    processed_map_image_data = HiddenField("Processed map image data")
    homepage_map_max_dimension = IntegerField(
        "Homepage map max size (px)",
        validators=[DataRequired(), NumberRange(min=400, max=8000)],
        default=2560,
    )
    node_display_max_dimension = IntegerField(
        "Node display image max size (px)",
        validators=[DataRequired(), NumberRange(min=400, max=8000)],
        default=2200,
    )
    node_map_max_dimension = IntegerField(
        "Node map image max size (px)",
        validators=[DataRequired(), NumberRange(min=400, max=8000)],
        default=2560,
    )
    node_photo_max_dimension = IntegerField(
        "Node photo max size (px)",
        validators=[DataRequired(), NumberRange(min=400, max=8000)],
        default=2200,
    )
    activity_image_max_dimension = IntegerField(
        "Activity image max size (px)",
        validators=[DataRequired(), NumberRange(min=400, max=8000)],
        default=1800,
    )
    google_maps_center_lat = DecimalField(
        "Google Maps center latitude",
        places=6,
        validators=[Optional(), NumberRange(min=-90, max=90)],
    )
    google_maps_center_lng = DecimalField(
        "Google Maps center longitude",
        places=6,
        validators=[Optional(), NumberRange(min=-180, max=180)],
    )
    google_maps_zoom = IntegerField(
        "Google Maps zoom",
        validators=[Optional(), NumberRange(min=1, max=22)],
        default=19,
    )
    submit = SubmitField("Save settings")


class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=80)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    preferred_locale = SelectField(
        "Language",
        choices=SUPPORTED_LOCALES,
        validators=[DataRequired()],
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=8, message="Use at least 8 characters.")],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[Optional(), EqualTo("password", message="Passwords must match.")],
    )
    is_active = BooleanField("User active", default=True)
    roles = SelectMultipleField("Roles", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Save user")

    def __init__(self, *args, user: User | None = None, **kwargs) -> None:
        """Store the edited user so uniqueness checks can ignore the same record.

        Parameters:
            *args: Positional arguments forwarded to the WTForms base class.
            user: Existing user being edited, if any.
            **kwargs: Keyword arguments forwarded to the WTForms base class.
        """
        super().__init__(*args, **kwargs)
        self.user = user

    def validate(self, extra_validators=None) -> bool:
        """Validate user data, including unique username and optional email.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        if not super().validate(extra_validators=extra_validators):
            return False

        if self.user is None and not self.password.data:
            self.password.errors.append("Password is required for new users.")
            return False

        self.username.data = self.username.data.strip()
        email_value = (self.email.data or "").strip().lower()
        self.email.data = email_value

        existing_username = User.query.filter_by(username=self.username.data).first()
        if existing_username and (self.user is None or existing_username.id != self.user.id):
            self.username.errors.append("Username already in use.")
            return False

        if email_value:
            existing_email = User.query.filter_by(email=email_value).first()
            if existing_email and (self.user is None or existing_email.id != self.user.id):
                self.email.errors.append("Email already in use.")
                return False

        return True


class HomeAssistantSettingsForm(FlaskForm):
    base_url = StringField("Base URL", validators=[Optional(), Length(max=255)])
    internal_url = StringField("Internal URL", validators=[Optional(), Length(max=255)])
    access_token = PasswordField(
        "Long-lived access token",
        validators=[Optional(), Length(max=255)],
    )
    user_agent = StringField("User-Agent", validators=[Optional(), Length(max=255)])
    verify_ssl = BooleanField("Verify SSL certificates", default=True)
    request_timeout = IntegerField(
        "Request timeout (seconds)",
        validators=[DataRequired(), NumberRange(min=1, max=120)],
        default=10,
    )
    submit = SubmitField("Save Home Assistant settings")

    def validate_base_url(self, field) -> None:
        """Validate the external Home Assistant URL field.

        Parameters:
            field: WTForms field instance being validated.
        """
        self._validate_url_field(field)

    def validate_internal_url(self, field) -> None:
        """Validate the internal Home Assistant URL field.

        Parameters:
            field: WTForms field instance being validated.
        """
        self._validate_url_field(field)

    def validate(self, extra_validators=None) -> bool:
        """Validate Home Assistant settings as a complete configuration.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        if not super().validate(extra_validators=extra_validators):
            return False

        base_url = (self.base_url.data or "").strip()
        internal_url = (self.internal_url.data or "").strip()
        access_token = (self.access_token.data or "").strip()

        if not (base_url or internal_url) and access_token:
            message = "Provide a Base URL or an Internal URL together with the long-lived access token."
            self.base_url.errors.append(message)
            self.internal_url.errors.append(message)
            self.access_token.errors.append(message)
            return False

        if (base_url or internal_url) and not access_token:
            message = "A long-lived access token is required when a Home Assistant URL is configured."
            self.access_token.errors.append(message)
            return False

        return True

    @staticmethod
    def _validate_url_field(field) -> None:
        """Ensure a URL field contains a full HTTP or HTTPS URL.

        Parameters:
            field: WTForms field instance being validated.
        """
        value = (field.data or "").strip()
        if not value:
            return

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError("Use a full URL like http://homeassistant.local:8123 or https://example.com.")


class ActionForm(FlaskForm):
    submit = SubmitField("Submit")


class ManagedMdiIconAddForm(FlaskForm):
    icon_name = HiddenField("Icon name", validators=[DataRequired(), Length(max=64)])
    tags_json = HiddenField("Icon tags")
    submit = SubmitField("Add icon")


class ProfileLanguageForm(FlaskForm):
    preferred_locale = SelectField(
        "Language",
        choices=SUPPORTED_LOCALES,
        validators=[DataRequired()],
    )
    submit = SubmitField("Save language")


class ActivityTypeForm(FlaskForm):
    name = StringField("Activity type name", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    tracks_quantity_kg = BooleanField("Track quantity in kg", default=False)
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    submit = SubmitField("Save activity type")


class LinkTypeForm(FlaskForm):
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    requires_label = BooleanField("Label required", default=False)
    requires_url = BooleanField("URL required", default=True)
    submit = SubmitField("Save link type")


class CultivationTypeForm(FlaskForm):
    botanical_name = StringField("Botanical name", validators=[Optional(), Length(max=160)])
    common_name = StringField("Common name", validators=[Optional(), Length(max=160)])
    life_cycle = SelectField(
        "Life cycle",
        choices=[
            ("", "Not set"),
            ("annual", "Annual"),
            ("perennial", "Perennial"),
        ],
        validators=[Optional()],
    )
    external_url = StringField("External URL", validators=[Optional(), URL(), Length(max=500)])
    default_marker_color_id = SelectField("Default marker color", coerce=int, validators=[Optional()], default=0)
    default_marker_icon = SelectField("Default marker icon", choices=[("", "No icon")], validators=[Optional()])
    submit = SubmitField("Save cultivation type")

    def validate(self, extra_validators=None) -> bool:
        """Validate cultivation type naming rules.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        if not super().validate(extra_validators=extra_validators):
            return False

        self.botanical_name.data = (self.botanical_name.data or "").strip()
        self.common_name.data = (self.common_name.data or "").strip()
        self.external_url.data = (self.external_url.data or "").strip()
        if not self.botanical_name.data and not self.common_name.data:
            message = "Add at least a botanical name or a common name."
            self.botanical_name.errors.append(message)
            self.common_name.errors.append(message)
            return False

        return True


class CultivationTypeImageForm(FlaskForm):
    title = StringField("Image title", validators=[Optional(), Length(max=120)])
    image = FileField(
        "Image",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    caption = TextAreaField("Caption", validators=[Optional(), Length(max=1000)])
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    submit = SubmitField("Save image")


class CultivationTypeVariantForm(FlaskForm):
    name = StringField("Variant name", validators=[DataRequired(), Length(max=160)])
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    default_marker_color_id = SelectField("Default marker color", coerce=int, validators=[Optional()], default=0)
    submit = SubmitField("Save variant")


class MarkerColorForm(FlaskForm):
    name = StringField("Color name", validators=[DataRequired(), Length(max=64)])
    hex_value = StringField("Hex color", validators=[DataRequired(), Length(max=16)])
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    submit = SubmitField("Save color")


class NodeForm(FlaskForm):
    title = StringField("Title", validators=[Optional(), Length(max=120)])
    cultivation_type_id = SelectField("Cultivation type", coerce=int, validators=[Optional()], default=0)
    cultivation_type_variant_id = SelectField("Cultivation variant", coerce=int, validators=[Optional()], default=0)
    node_type = SelectField(
        "Type",
        choices=[
            ("area", "Area"),
            ("section", "Section"),
            ("bed", "Bed"),
            ("plant", "Plant"),
            ("custom", "Custom"),
        ],
        validators=[DataRequired()],
    )
    summary = TextAreaField("Summary", validators=[Optional(), Length(max=1000)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=5000)])
    quantity = IntegerField(
        "Quantity",
        validators=[Optional(), NumberRange(min=1, max=100000)],
        default=1,
    )
    life_cycle = SelectField(
        "Life cycle",
        choices=[
            ("", "Not set"),
            ("annual", "Annual"),
            ("perennial", "Perennial"),
        ],
        validators=[Optional()],
    )
    cultivation_year = IntegerField(
        "Cultivation year",
        validators=[Optional(), NumberRange(min=1900, max=2100)],
    )
    planting_date = DateField("Planting date", validators=[Optional()], format="%Y-%m-%d")
    death_year = IntegerField(
        "Death year",
        validators=[Optional(), NumberRange(min=1900, max=2100)],
    )
    hero_image = FileField(
        "Hero image",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    processed_hero_image_data = HiddenField("Processed hero image data")
    hero_image_role = SelectField(
        "Image usage",
        choices=[
            ("display", "Display"),
            ("map", "Map"),
        ],
        validators=[DataRequired()],
        default="display",
    )
    image_display_mode = SelectField(
        "Image display mode",
        choices=[
            ("contain", "Show full image"),
            ("cover", "Crop to fill"),
        ],
        validators=[DataRequired()],
    )
    image_focus_x = DecimalField(
        "Crop focus X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=50,
    )
    image_focus_y = DecimalField(
        "Crop focus Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=50,
    )
    map_x = DecimalField(
        "Map X position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    map_y = DecimalField(
        "Map Y position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    overlay_shape = SelectField(
        "Overlay type",
        choices=[
            ("point", "Point"),
            ("area", "Area"),
        ],
        validators=[DataRequired()],
    )
    overlay_width = DecimalField(
        "Area width (%)",
        places=2,
        validators=[Optional(), NumberRange(min=1, max=100)],
        default=18,
    )
    overlay_height = DecimalField(
        "Area height (%)",
        places=2,
        validators=[Optional(), NumberRange(min=1, max=100)],
        default=12,
    )
    additional_positions_json = HiddenField("Additional positions")
    area_corner_1_x = DecimalField(
        "Area corner 1 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_1_y = DecimalField(
        "Area corner 1 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_2_x = DecimalField(
        "Area corner 2 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_2_y = DecimalField(
        "Area corner 2 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_3_x = DecimalField(
        "Area corner 3 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_3_y = DecimalField(
        "Area corner 3 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_4_x = DecimalField(
        "Area corner 4 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_4_y = DecimalField(
        "Area corner 4 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    marker_color_id = SelectField(
        "Marker color",
        coerce=int,
        validators=[DataRequired()],
    )
    marker_icon = StringField(
        "Marker icon",
        validators=[Optional(), Length(max=64)],
    )
    geo_lat = DecimalField(
        "Latitude",
        places=6,
        validators=[Optional(), NumberRange(min=-90, max=90)],
    )
    geo_lng = DecimalField(
        "Longitude",
        places=6,
        validators=[Optional(), NumberRange(min=-180, max=180)],
    )
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    is_published = BooleanField("Published", default=True)
    submit = SubmitField("Save node")

    def __init__(
        self,
        *args,
        cultivation_types_by_id: dict[int, object] | None = None,
        cultivation_variants_by_id: dict[int, object] | None = None,
        **kwargs,
    ) -> None:
        """Store cultivation type metadata used during node validation.

        Parameters:
            *args: Positional arguments forwarded to the WTForms base class.
            cultivation_types_by_id: Cultivation type lookup keyed by database id.
            cultivation_variants_by_id: Cultivation variant lookup keyed by database id.
            **kwargs: Keyword arguments forwarded to the WTForms base class.
        """
        super().__init__(*args, **kwargs)
        self.cultivation_types_by_id = cultivation_types_by_id or {}
        self.cultivation_variants_by_id = cultivation_variants_by_id or {}

    def validate(self, extra_validators=None) -> bool:
        """Validate node data, including annual cultivation year rules.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        # These image framing fields are no longer exposed in the node form,
        # so keep them on sensible defaults when older submissions omit them.
        if not (self.hero_image_role.data or "").strip():
            self.hero_image_role.data = "display"
        if not (self.image_display_mode.data or "").strip():
            self.image_display_mode.data = "contain"
        if self.image_focus_x.data is None:
            self.image_focus_x.data = 50
        if self.image_focus_y.data is None:
            self.image_focus_y.data = 50

        if not super().validate(extra_validators=extra_validators):
            return False

        is_cultivation_node = self.node_type.data in {"bed", "plant"}
        selected_cultivation_type = self.cultivation_types_by_id.get(self.cultivation_type_id.data or 0)
        selected_variant = self.cultivation_variants_by_id.get(self.cultivation_type_variant_id.data or 0)
        if not is_cultivation_node:
            self.cultivation_type_id.data = 0
            self.cultivation_type_variant_id.data = 0
            selected_cultivation_type = None
            selected_variant = None
        elif selected_cultivation_type is None:
            self.cultivation_type_id.errors.append("Choose a cultivation type.")
            return False
        else:
            if not (self.title.data or "").strip():
                self.title.data = selected_cultivation_type.default_node_title_for_variant(
                    selected_variant.name if selected_variant is not None else None
                )
            self.life_cycle.data = selected_cultivation_type.life_cycle or ""
            if selected_variant is not None and selected_variant.cultivation_type_id != selected_cultivation_type.id:
                self.cultivation_type_variant_id.errors.append("Choose a variant that belongs to the selected cultivation type.")
                return False
            if selected_variant is None and getattr(selected_cultivation_type, "variants", None):
                self.cultivation_type_variant_id.errors.append("Choose one variant for this cultivation type.")
                return False

        self.title.data = (self.title.data or "").strip()
        if not self.title.data:
            self.title.errors.append("Title is required.")
            return False

        if self.life_cycle.data == "annual" and self.node_type.data != "section":
            if self.cultivation_year.data is None and self.planting_date.data is None:
                self.cultivation_year.errors.append(
                    "Annual cultivations need a cultivation year or planting date."
                )
                return False

            if self.cultivation_year.data is None and self.planting_date.data is not None:
                self.cultivation_year.data = self.planting_date.data.year

            if (
                self.cultivation_year.data is not None
                and self.planting_date.data is not None
                and self.cultivation_year.data < self.planting_date.data.year
            ):
                self.cultivation_year.errors.append(
                    "Cultivation year cannot be earlier than the planting year."
                )
                return False

        return True


class PhotoForm(FlaskForm):
    image = FileField(
        "Image",
        validators=[DataRequired(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    title = StringField("Photo title", validators=[Optional(), Length(max=120)])
    image_role = SelectField(
        "Use image as",
        choices=PHOTO_ROLE_CHOICES,
        default="prospect",
        validators=[DataRequired()],
    )
    caption = TextAreaField("Caption", validators=[Optional(), Length(max=1000)])
    processed_image_data = HiddenField("Processed image data")
    submit = SubmitField("Save image")


class PhotoEditForm(FlaskForm):
    title = StringField("Photo title", validators=[DataRequired(), Length(max=120)])
    image_role = SelectField(
        "Use image as",
        choices=PHOTO_ROLE_CHOICES,
        default="prospect",
        validators=[DataRequired()],
    )
    image = FileField(
        "Image",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    caption = TextAreaField("Caption", validators=[Optional(), Length(max=1000)])
    taken_at = DateField("Taken on", validators=[DataRequired()], format="%Y-%m-%d")
    is_default = BooleanField("Use as default image", default=False)
    sort_order = IntegerField("Sort order", validators=[Optional()], default=0)
    processed_image_data = HiddenField("Processed image data")
    submit = SubmitField("Save photo")


class NodeImageEditForm(FlaskForm):
    image = FileField(
        "Image",
        validators=[DataRequired(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    processed_image_data = HiddenField("Processed image data")
    submit = SubmitField("Save image")


class NodeActivityForm(FlaskForm):
    activity_type_id = SelectField("Activity type", coerce=int, validators=[DataRequired()])
    happened_on = DateField("Date", validators=[DataRequired()], format="%Y-%m-%d")
    quantity_kg = DecimalField(
        "Quantity (kg)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=1000000)],
    )
    description = TextAreaField("Description", validators=[DataRequired(), Length(max=4000)])
    image = FileField(
        "Image",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, "Images only.")],
    )
    processed_image_data = HiddenField("Processed image data")
    submit = SubmitField("Save activity")

    def __init__(self, *args, activity_types_by_id: dict[int, object] | None = None, **kwargs) -> None:
        """Store activity type metadata used during cross-field validation.

        Parameters:
            *args: Positional arguments forwarded to the WTForms base class.
            activity_types_by_id: Activity type lookup keyed by database id.
            **kwargs: Keyword arguments forwarded to the WTForms base class.
        """
        super().__init__(*args, **kwargs)
        self.activity_types_by_id = activity_types_by_id or {}

    def validate(self, extra_validators=None) -> bool:
        """Validate activity data, including required kilogram quantities.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        if not super().validate(extra_validators=extra_validators):
            return False

        activity_type = self.activity_types_by_id.get(self.activity_type_id.data)
        if (
            activity_type is not None
            and getattr(activity_type, "tracks_quantity_kg", False)
            and self.quantity_kg.data is None
        ):
            self.quantity_kg.errors.append("Quantity in kg is required for this activity type.")
            return False

        return True


class ExternalLinkForm(FlaskForm):
    link_type_id = SelectField(
        "Link type",
        coerce=int,
        validators=[DataRequired()],
    )
    label = StringField("Link label", validators=[Optional(), Length(max=120)])
    url = StringField("URL", validators=[Optional(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Add link")

    def __init__(self, *args, link_types_by_id: dict[int, object] | None = None, **kwargs) -> None:
        """Store link type metadata used during cross-field validation.

        Parameters:
            *args: Positional arguments forwarded to the WTForms base class.
            link_types_by_id: Link type lookup keyed by database id.
            **kwargs: Keyword arguments forwarded to the WTForms base class.
        """
        super().__init__(*args, **kwargs)
        self.link_types_by_id = link_types_by_id or {}

    def validate(self, extra_validators=None) -> bool:
        """Validate link data against the selected link type rules.

        Parameters:
            extra_validators: Additional WTForms validators supplied by Flask-WTF.
        """
        if not super().validate(extra_validators=extra_validators):
            return False

        link_type = self.link_types_by_id.get(self.link_type_id.data)
        if (
            link_type is not None
            and getattr(link_type, "requires_label", False)
            and not (self.label.data or "").strip()
        ):
            self.label.errors.append("A label is required for this link type.")
            return False

        url_value = (self.url.data or "").strip()
        if link_type is not None and getattr(link_type, "requires_url", True) and not url_value:
            self.url.errors.append("A URL is required for this link type.")
            return False

        if url_value:
            validator = URL(message="Enter a valid URL.")
            try:
                validator(self, self.url)
            except ValidationError as exc:
                self.url.errors.append(str(exc))
                return False

        return True


class HomeAssistantEntityForm(FlaskForm):
    discovered_entity = SelectField(
        "Discovered entity",
        coerce=int,
        validators=[DataRequired()],
    )
    label = StringField("Friendly name", validators=[Optional(), Length(max=120)])
    show_on_image = BooleanField("Show on image", default=False)
    map_x = DecimalField(
        "Image X position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    map_y = DecimalField(
        "Image Y position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Add entity")


class IrrigationZoneForm(FlaskForm):
    name = StringField("Zone name", validators=[DataRequired(), Length(max=120)])
    discovered_entity = SelectField(
        "Discovered entity",
        coerce=int,
        validators=[Optional()],
    )
    overlay_color = SelectField(
        "Overlay color",
        choices=[],
        default=DEFAULT_IRRIGATION_ZONE_COLOR,
        validators=[DataRequired()],
    )
    texture_pattern = SelectField(
        "Texture pattern",
        choices=[],
        default=DEFAULT_IRRIGATION_ZONE_TEXTURE,
        validators=[DataRequired()],
    )
    map_x = DecimalField(
        "Image X position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    map_y = DecimalField(
        "Image Y position (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    overlay_width = DecimalField(
        "Area width (%)",
        places=2,
        validators=[Optional(), NumberRange(min=1, max=100)],
        default=18,
    )
    overlay_height = DecimalField(
        "Area height (%)",
        places=2,
        validators=[Optional(), NumberRange(min=1, max=100)],
        default=12,
    )
    area_corner_1_x = DecimalField(
        "Area corner 1 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_1_y = DecimalField(
        "Area corner 1 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_2_x = DecimalField(
        "Area corner 2 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_2_y = DecimalField(
        "Area corner 2 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_3_x = DecimalField(
        "Area corner 3 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_3_y = DecimalField(
        "Area corner 3 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_4_x = DecimalField(
        "Area corner 4 X (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    area_corner_4_y = DecimalField(
        "Area corner 4 Y (%)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    subzone_rectangles_json = HiddenField("Internal rectangles")
    submit = SubmitField("Save irrigation zone")


class DeleteForm(FlaskForm):
    remove_files = BooleanField("Also remove uploaded files", default=False)
    submit = SubmitField("Delete")
