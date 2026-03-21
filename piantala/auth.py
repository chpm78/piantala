from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect

from .extensions import db
from .forms import LoginForm
from .models import GardenSettings, User


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
