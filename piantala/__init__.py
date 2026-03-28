from pathlib import Path
import tomllib
from importlib.metadata import PackageNotFoundError, version as package_version

import click
from dotenv import load_dotenv
from flask import Flask, request
from flask_login import current_user
from sqlalchemy import inspect

from .config import Config
from .extensions import db, login_manager
from .media import max_dimension_for_kind, optimize_image_file, relative_upload_to_fs_path
from .models import (
    GardenNode,
    GardenSettings,
    NodeActivityImage,
    NodePhoto,
    Role,
    TranslationEntry,
    User,
    ensure_seed_data,
    sync_schema,
)
from .translations import DEFAULT_LOCALE, SUPPORTED_LOCALES


def _project_version() -> str:
    """Return the current Piantala version declared by the source tree.

    The web UI should reflect the version of the checked-out project, even when
    the installed package metadata is stale in an existing virtualenv.
    """
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as pyproject_file:
            project_data = tomllib.load(pyproject_file)
        version = project_data.get("project", {}).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        pass

    try:
        return package_version("piantala")
    except PackageNotFoundError:
        return "unknown"


def _move_upload_if_needed(upload_dir: Path, current_path: str | None, target_path: str) -> str:
    """Move one stored upload into a new relative location when needed.

    Parameters:
        upload_dir: Absolute upload directory configured for the app.
        current_path: Existing stored relative path, if any.
        target_path: Desired stored relative path under `uploads/...`.
    """
    if not current_path or current_path == target_path:
        return target_path

    source_path = relative_upload_to_fs_path(upload_dir, current_path)
    target_file_path = relative_upload_to_fs_path(upload_dir, target_path)
    if not source_path.exists():
        return current_path

    target_file_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path != target_file_path:
        source_path.replace(target_file_path)
    return target_path


def _organize_upload_folders(upload_dir: Path) -> int:
    """Move stored uploads into structured folders and update DB paths.

    Parameters:
        upload_dir: Absolute upload directory configured for the app.
    """
    moved_count = 0
    settings = GardenSettings.get_or_create()
    if settings.map_image_path:
        target_path = f"uploads/site/{Path(settings.map_image_path).name}"
        new_path = _move_upload_if_needed(upload_dir, settings.map_image_path, target_path)
        if new_path != settings.map_image_path:
            settings.map_image_path = new_path
            moved_count += 1

    for node in GardenNode.query.all():
        if node.hero_image_path:
            target_path = f"uploads/nodes/{node.id}/{Path(node.hero_image_path).name}"
            new_path = _move_upload_if_needed(upload_dir, node.hero_image_path, target_path)
            if new_path != node.hero_image_path:
                node.hero_image_path = new_path
                moved_count += 1
        if node.map_image_path:
            target_path = f"uploads/nodes/{node.id}/{Path(node.map_image_path).name}"
            new_path = _move_upload_if_needed(upload_dir, node.map_image_path, target_path)
            if new_path != node.map_image_path:
                node.map_image_path = new_path
                moved_count += 1

    for photo in NodePhoto.query.all():
        target_path = f"uploads/nodes/{photo.node_id}/{Path(photo.image_path).name}"
        new_path = _move_upload_if_needed(upload_dir, photo.image_path, target_path)
        if new_path != photo.image_path:
            photo.image_path = new_path
            moved_count += 1

    for image in NodeActivityImage.query.all():
        target_path = f"uploads/nodes/{image.activity.node_id}/{Path(image.image_path).name}"
        new_path = _move_upload_if_needed(upload_dir, image.image_path, target_path)
        if new_path != image.image_path:
            image.image_path = new_path
            moved_count += 1

    if moved_count:
        db.session.commit()
    return moved_count


def create_app() -> Flask:
    """Create and configure the Flask application instance."""
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        sync_schema()
        ensure_seed_data()
        settings = GardenSettings.get_or_create()
        upload_dir = Path(app.config["UPLOAD_FOLDER"])
        moved_count = _organize_upload_folders(upload_dir)
        if moved_count:
            app.logger.info("Reorganized %s upload paths into per-node folders.", moved_count)
        optimization_targets: dict[str, int] = {}

        for path in [
            path
            for (path,) in db.session.query(GardenSettings.map_image_path)
            .filter(GardenSettings.map_image_path.isnot(None))
            .all()
        ]:
            optimization_targets[path] = max(
                optimization_targets.get(path, 0),
                max_dimension_for_kind(settings, "homepage_map"),
            )

        for path in [
            path
            for (path,) in db.session.query(GardenNode.hero_image_path)
            .filter(GardenNode.hero_image_path.isnot(None))
            .all()
        ]:
            optimization_targets[path] = max(
                optimization_targets.get(path, 0),
                max_dimension_for_kind(settings, "node_display"),
            )

        for path in [
            path
            for (path,) in db.session.query(GardenNode.map_image_path)
            .filter(GardenNode.map_image_path.isnot(None))
            .all()
        ]:
            optimization_targets[path] = max(
                optimization_targets.get(path, 0),
                max_dimension_for_kind(settings, "node_map"),
            )

        for path in [path for (path,) in db.session.query(NodePhoto.image_path).all()]:
            optimization_targets[path] = max(
                optimization_targets.get(path, 0),
                max_dimension_for_kind(settings, "node_photo"),
            )

        for path in [path for (path,) in db.session.query(NodeActivityImage.image_path).all()]:
            optimization_targets[path] = max(
                optimization_targets.get(path, 0),
                max_dimension_for_kind(settings, "activity_image"),
            )

        optimized_count = 0
        for relative_path, max_dimension in optimization_targets.items():
            file_path = relative_upload_to_fs_path(upload_dir, relative_path)
            if optimize_image_file(
                file_path,
                max_dimension=max_dimension,
                jpeg_quality=app.config["IMAGE_JPEG_QUALITY"],
                size_threshold=app.config["IMAGE_REPAIR_SIZE_THRESHOLD"],
            ):
                optimized_count += 1
        if optimized_count:
            app.logger.info("Optimized %s uploaded images during startup repair.", optimized_count)

    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.get("/healthz")
    def healthcheck() -> tuple[dict[str, str], int]:
        """Return a lightweight health response for Docker and uptime checks."""
        return {"status": "ok"}, 200

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        """Load a logged-in user from the Flask-Login session id.

        Parameters:
            user_id: User identifier stored in the session cookie.
        """
        if not user_id.isdigit():
            return None
        return db.session.get(User, int(user_id))

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create database tables, run schema sync, and seed system records."""
        db.create_all()
        sync_schema()
        ensure_seed_data()
        click.echo("Database initialized and system roles seeded.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", default="", help="Optional email address.")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_command(username: str, email: str, password: str) -> None:
        """Create the first admin user from the command line.

        Parameters:
            username: Login name assigned to the new admin user.
            email: Optional email address for the new admin user.
            password: Plain-text password entered via the CLI prompt.
        """
        db.create_all()
        sync_schema()
        ensure_seed_data()

        username = username.strip()
        email = email.strip().lower()

        existing_user = User.query.filter(User.username == username).first()
        if not existing_user and email:
            existing_user = User.query.filter(User.email == email).first()
        if existing_user:
            raise click.ClickException("A user with that username or email already exists.")

        admin_role = Role.query.filter_by(name="admin").first()
        if admin_role is None:
            raise click.ClickException("Admin role missing. Run `flask --app app init-db` first.")

        user = User(username=username, email=email or None, is_active=True)
        user.set_password(password)
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin user `{username}` created.")

    @app.context_processor
    def inject_globals() -> dict[str, str | bool]:
        """Expose commonly used settings and translation helpers to templates."""
        site_name = "Piantala"
        app_version = _project_version()
        load_leaflet = False
        app_theme = "earth"
        app_font = "classic_serif"
        current_locale = DEFAULT_LOCALE
        localized_entries: dict[str, str] = {}
        fallback_entries: dict[str, str] = {}
        try:
            if inspect(db.engine).has_table(GardenSettings.__tablename__):
                settings = GardenSettings.get_or_create()
                site_name = settings.site_name
                load_leaflet = settings.map_provider in {"openstreetmap", "opentopomap"}
                app_theme = settings.color_scheme
                app_font = settings.font_family

            supported_codes = [code for code, _label in SUPPORTED_LOCALES]
            if current_user.is_authenticated and current_user.preferred_locale in supported_codes:
                current_locale = current_user.preferred_locale
            else:
                browser_locale = request.accept_languages.best_match(supported_codes)
                current_locale = browser_locale or DEFAULT_LOCALE

            if inspect(db.engine).has_table(TranslationEntry.__tablename__):
                localized_entries = {
                    entry.key: entry.text
                    for entry in TranslationEntry.query.filter_by(locale=current_locale).all()
                }
                fallback_entries = {
                    entry.key: entry.text
                    for entry in TranslationEntry.query.filter_by(locale=DEFAULT_LOCALE).all()
                }
        except Exception:
            pass

        def tr(key: str, default: str | None = None) -> str:
            """Resolve one translation key for templates.

            Parameters:
                key: Translation key requested by the template.
                default: Fallback text used when no translation is available.
            """
            return localized_entries.get(key) or fallback_entries.get(key) or default or key

        return {
            "site_name": site_name,
            "app_version": app_version,
            "google_maps_api_key": app.config["GOOGLE_MAPS_API_KEY"],
            "google_maps_enabled": bool(app.config["GOOGLE_MAPS_API_KEY"]),
            "load_leaflet": load_leaflet,
            "app_theme": app_theme,
            "app_font": app_font,
            "current_locale": current_locale,
            "available_locales": SUPPORTED_LOCALES,
            "tr": tr,
        }

    return app
