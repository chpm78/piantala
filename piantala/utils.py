from __future__ import annotations

from functools import wraps
from pathlib import Path
from uuid import uuid4

from flask import abort, current_app, flash
from flask_login import current_user
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


LEVEL_TYPE_DEFAULTS = {
    1: "area",
    2: "section",
    3: "bed",
    4: "plant",
}


def save_uploaded_file(file_storage: FileStorage | None, prefix: str) -> str | None:
    if file_storage is None or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    extension = Path(filename).suffix.lower()
    unique_name = f"{prefix}-{uuid4().hex}{extension}"
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / unique_name
    file_storage.save(destination)
    return f"uploads/{unique_name}"


def permission_required(permission_code: str):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_permission(permission_code):
                flash("You do not have permission for that action.", "danger")
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def default_node_type(level: int) -> str:
    return LEVEL_TYPE_DEFAULTS.get(level, "custom")

