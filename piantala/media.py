from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - graceful runtime fallback
    Image = None


EXIF_DATE_TAGS = (36867, 36868, 306)
EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"


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
