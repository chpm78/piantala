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


def save_uploaded_file(
    file_storage: FileStorage | None,
    prefix: str,
    *,
    image_kind: str = "node_photo",
    subfolder: str | None = None,
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
    optimize_image_file(
        destination,
        max_dimension=max_dimension_for_kind(settings, image_kind),
        jpeg_quality=current_app.config["IMAGE_JPEG_QUALITY"],
        size_threshold=0,
        force=True,
    )
    return f"uploads/{destination.relative_to(upload_dir).as_posix()}"


def save_data_url_upload(
    data_url: str | None,
    prefix: str,
    *,
    image_kind: str = "node_photo",
    subfolder: str | None = None,
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
    optimize_image_file(
        destination,
        max_dimension=max_dimension_for_kind(settings, image_kind),
        jpeg_quality=current_app.config["IMAGE_JPEG_QUALITY"],
        size_threshold=0,
        force=True,
    )
    return f"uploads/{destination.relative_to(upload_dir).as_posix()}"


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
