from datetime import datetime, UTC

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect

from .extensions import db
from .forms import LoginForm, ProfileLanguageForm
from .models import GardenSettings, User, UserLoginHistory


bp = Blueprint("auth", __name__, url_prefix="/auth")


def _settings_or_none():
    try:
        if inspect(db.engine).has_table(GardenSettings.__tablename__):
            return GardenSettings.get_or_create()
    except Exception:
        return None
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.now(UTC)
            forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
            db.session.add(
                UserLoginHistory(
                    user=user,
                    logged_in_at=user.last_login_at,
                    ip_address=(forwarded_for or request.remote_addr or "")[:64] or None,
                    user_agent=(request.user_agent.string or "")[:512] or None,
                )
            )
            db.session.commit()
            flash("Logged in.", "success")
            return redirect(url_for("main.index"))
        flash("Invalid username or password.", "danger")

    return render_template("login.html", form=form, settings=_settings_or_none())


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileLanguageForm(obj=current_user)

    if form.validate_on_submit():
        current_user.preferred_locale = form.preferred_locale.data
        db.session.commit()
        flash("Language updated.", "success")
        return redirect(url_for("auth.profile"))

    return render_template(
        "profile_form.html",
        form=form,
        settings=_settings_or_none(),
    )
