from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from tempfile import NamedTemporaryFile

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - graceful runtime fallback
    Image = None
    ImageOps = None


EXIF_DATE_TAGS = (36867, 36868, 306)
EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"
OPTIMIZABLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_KIND_DEFAULTS = {
    "homepage_map": 2560,
    "node_display": 2200,
    "node_map": 2560,
    "node_photo": 2200,
    "activity_image": 1800,
}


def relative_upload_to_fs_path(upload_dir: Path, relative_path: str) -> Path:
    """Resolve one stored `uploads/...` path inside the configured upload dir.

    Parameters:
        upload_dir: Absolute upload directory configured by the application.
        relative_path: Stored relative path, usually starting with `uploads/`.
    """
    normalized = relative_path.removeprefix("uploads/").lstrip("/")
    return upload_dir / Path(normalized)


def filename_stem(filename: str | None) -> str:
    """Convert an uploaded filename into a human-friendly default title.

    Parameters:
        filename: Original file name supplied by the user agent.
    """
    if not filename:
        return "Photo"
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return stem or "Photo"


def extract_exif_taken_at(file_storage) -> datetime | None:
    """Read the capture timestamp from EXIF metadata when available.

    Parameters:
        file_storage: Uploaded image file to inspect.
    """
    if Image is None or file_storage is None:
        return None

    stream = file_storage.stream
    current_position = stream.tell()

    try:
        stream.seek(0)
        with Image.open(stream) as image:
            exif = image.getexif()
            if not exif:
                return None

            for tag in EXIF_DATE_TAGS:
                value = exif.get(tag)
                if not value:
                    continue
                try:
                    return datetime.strptime(str(value), EXIF_DATETIME_FORMAT).replace(tzinfo=UTC)
                except ValueError:
                    continue
    except Exception:
        return None
    finally:
        stream.seek(current_position)

    return None


def optimize_image_file(
    image_path: Path,
    *,
    max_dimension: int,
    jpeg_quality: int,
    size_threshold: int = 0,
    force: bool = False,
) -> bool:
    """Resize and recompress one uploaded image when it is too large.

    Parameters:
        image_path: Absolute path of the image file to optimize in place.
        max_dimension: Maximum width or height allowed after resizing.
        jpeg_quality: JPEG/WebP quality used for lossy output formats.
        size_threshold: Minimum file size in bytes that triggers repair mode.
        force: When True, optimize even if the file is already under thresholds.
    """
    if Image is None or not image_path.exists() or image_path.suffix.lower() not in OPTIMIZABLE_EXTENSIONS:
        return False

    try:
        original_size = image_path.stat().st_size
        with Image.open(image_path) as opened_image:
            image = ImageOps.exif_transpose(opened_image) if ImageOps is not None else opened_image.copy()
            image.load()
            source_format = (opened_image.format or image_path.suffix.lstrip(".")).upper()
    except Exception:
        return False

    width, height = image.size
    needs_resize = max(width, height) > max_dimension
    if not force and not needs_resize and original_size <= size_threshold:
        return False

    working_image = image.copy()
    temp_path: Path | None = None
    try:
        if needs_resize:
            working_image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        with NamedTemporaryFile(delete=False, suffix=image_path.suffix, dir=image_path.parent) as temp_file:
            temp_path = Path(temp_file.name)

        save_kwargs: dict[str, object] = {"optimize": True}
        output_format = source_format

        if source_format in {"JPG", "JPEG"}:
            if working_image.mode not in {"RGB", "L"}:
                working_image = working_image.convert("RGB")
            output_format = "JPEG"
            save_kwargs.update({"quality": jpeg_quality, "progressive": True})
        elif source_format == "PNG":
            if working_image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                working_image = working_image.convert("RGBA")
            save_kwargs.update({"compress_level": 9})
            output_format = "PNG"
        elif source_format == "WEBP":
            if working_image.mode not in {"RGB", "RGBA", "L", "LA"}:
                working_image = working_image.convert("RGBA")
            save_kwargs.update({"quality": jpeg_quality, "method": 6})
            output_format = "WEBP"

        working_image.save(temp_path, format=output_format, **save_kwargs)
        optimized_size = temp_path.stat().st_size
        if not force and not needs_resize and optimized_size >= original_size:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return False

        temp_path.replace(image_path)
        return True
    except Exception:
        try:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False
    finally:
        try:
            working_image.close()
        except Exception:
            pass
        try:
            image.close()
        except Exception:
            pass


def repair_uploaded_images(
    upload_dir: Path,
    relative_paths: list[str],
    *,
    max_dimension: int,
    jpeg_quality: int,
    size_threshold: int,
) -> int:
    """Optimize older uploaded images that are still larger than desired.

    Parameters:
        upload_dir: Absolute upload directory configured by the application.
        relative_paths: Relative `uploads/...` paths stored in the database.
        max_dimension: Maximum width or height allowed after resizing.
        jpeg_quality: JPEG/WebP quality used for lossy output formats.
        size_threshold: Minimum file size in bytes that triggers repair mode.
    """
    optimized_count = 0
    seen_paths: set[Path] = set()
    for relative_path in relative_paths:
        if not relative_path:
            continue
        file_path = relative_upload_to_fs_path(upload_dir, relative_path)
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        if optimize_image_file(
            file_path,
            max_dimension=max_dimension,
            jpeg_quality=jpeg_quality,
            size_threshold=size_threshold,
        ):
            optimized_count += 1
    return optimized_count


def max_dimension_for_kind(settings, image_kind: str) -> int:
    """Return the configured max image dimension for one upload category.

    Parameters:
        settings: Garden settings instance containing image-size preferences.
        image_kind: Logical upload category such as `node_photo` or `node_map`.
    """
    mapping = {
        "homepage_map": getattr(settings, "homepage_map_max_dimension", IMAGE_KIND_DEFAULTS["homepage_map"]),
        "node_display": getattr(settings, "node_display_max_dimension", IMAGE_KIND_DEFAULTS["node_display"]),
        "node_map": getattr(settings, "node_map_max_dimension", IMAGE_KIND_DEFAULTS["node_map"]),
        "node_photo": getattr(settings, "node_photo_max_dimension", IMAGE_KIND_DEFAULTS["node_photo"]),
        "activity_image": getattr(settings, "activity_image_max_dimension", IMAGE_KIND_DEFAULTS["activity_image"]),
    }
    return int(mapping.get(image_kind, IMAGE_KIND_DEFAULTS["node_photo"]))


def collect_referenced_upload_paths() -> set[str]:
    """Return every upload path currently referenced by the Piantala database."""
    from .extensions import db
    from .models import GardenNode, GardenSettings, NodeActivityImage, NodePhoto

    referenced_paths: set[str] = set()
    settings = GardenSettings.get_or_create()
    if settings.map_image_path:
        referenced_paths.add(settings.map_image_path)

    for path in (
        db.session.query(GardenNode.hero_image_path)
        .filter(GardenNode.hero_image_path.isnot(None))
        .all()
    ):
        referenced_paths.add(path[0])
    for path in (
        db.session.query(GardenNode.map_image_path)
        .filter(GardenNode.map_image_path.isnot(None))
        .all()
    ):
        referenced_paths.add(path[0])
    for path in db.session.query(NodePhoto.image_path).all():
        referenced_paths.add(path[0])
    for path in db.session.query(NodeActivityImage.image_path).all():
        referenced_paths.add(path[0])
    return referenced_paths


def remove_unreferenced_uploads(upload_dir: Path, relative_paths: set[str]) -> int:
    """Delete upload files that are no longer referenced anywhere in the DB.

    Parameters:
        upload_dir: Absolute upload directory configured by the application.
        relative_paths: Candidate relative `uploads/...` paths to remove.
    """
    referenced_paths = collect_referenced_upload_paths()
    removed_count = 0
    for relative_path in relative_paths:
        if not relative_path or relative_path in referenced_paths:
            continue
        file_path = relative_upload_to_fs_path(upload_dir, relative_path)
        try:
            if file_path.exists():
                file_path.unlink()
                removed_count += 1
        except OSError:
            continue
    return removed_count
