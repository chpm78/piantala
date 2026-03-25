from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, request
from flask_login import current_user
from sqlalchemy import inspect

from .config import Config
from .extensions import db, login_manager
from .models import GardenSettings, Role, TranslationEntry, User, ensure_seed_data, sync_schema
from .translations import DEFAULT_LOCALE, SUPPORTED_LOCALES


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
