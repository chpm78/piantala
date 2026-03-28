from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'instance' / 'piantala.db'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        str(BASE_DIR / "piantala" / "static" / "uploads"),
    )
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
    IMAGE_MAX_DIMENSION = int(os.getenv("IMAGE_MAX_DIMENSION", "2560"))
    IMAGE_JPEG_QUALITY = int(os.getenv("IMAGE_JPEG_QUALITY", "85"))
    IMAGE_REPAIR_SIZE_THRESHOLD = int(os.getenv("IMAGE_REPAIR_SIZE_THRESHOLD", str(1_500_000)))
