from __future__ import annotations

from datetime import datetime, UTC
from urllib.parse import urljoin

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect

from .extensions import db
from .forms import InvitationRegistrationForm, LoginForm, ProfileLanguageForm, RegisterForm
from .mailing import MailError, send_email
from .models import (
    AuthToken,
    GardenSettings,
    PlatformSettings,
    Role,
    Site,
    SiteMembership,
    User,
    UserLoginHistory,
)
from .site_context import clear_current_site, current_site, ensure_current_site, set_current_site


bp = Blueprint("auth", __name__, url_prefix="/auth")


def _settings_or_none():
    """Return current-site settings when the table is available, otherwise None."""
    try:
        if inspect(db.engine).has_table(GardenSettings.__tablename__):
            return GardenSettings.get_or_create(current_site())
    except Exception:
        return None
    return None


def _platform_settings_or_none():
    """Return platform settings when the table is available, otherwise None."""
    try:
        if inspect(db.engine).has_table(PlatformSettings.__tablename__):
            return PlatformSettings.get_or_create()
    except Exception:
        return None
    return None


def _build_external_url(endpoint: str, **values) -> str:
    """Build one public absolute URL for links sent by email.

    Parameters:
        endpoint: Flask endpoint name.
        **values: URL variables forwarded to ``url_for``.
    """
    settings = PlatformSettings.get_or_create()
    absolute = url_for(endpoint, _external=True, **values)
    if not settings.public_base_url:
        return absolute
    relative = url_for(endpoint, _external=False, **values)
    return urljoin(settings.public_base_url.rstrip("/") + "/", relative.lstrip("/"))


def _record_login(user: User) -> None:
    """Record one successful login for auditing.

    Parameters:
        user: User who just authenticated.
    """
    login_user(user, remember=False)
    ensure_current_site()
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


def _membership_accept(token: AuthToken, user: User) -> SiteMembership:
    """Create one site membership from an invitation token when missing.

    Parameters:
        token: Invitation token being consumed.
        user: User joining the site.
    """
    membership = SiteMembership.query.filter_by(site_id=token.site_id, user_id=user.id).first()
    if membership is None:
        role = token.role or Role.query.filter_by(name="viewer").first()
        membership = SiteMembership(
            site=token.site,
            user=user,
            role=role,
        )
        db.session.add(membership)
    if user.email and user.email_confirmed_at is None:
        user.email_confirmed_at = datetime.now(UTC)
    token.used_at = datetime.now(UTC)
    if token.site is not None:
        set_current_site(token.site)
    return membership


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate a user, enforce email confirmation, and record a login history entry."""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        user = (
            User.query.filter_by(username=identifier).first()
            or User.query.filter_by(email=identifier.lower()).first()
        )
        if user and user.is_active and user.check_password(form.password.data):
            if user.email and user.email_confirmed_at is None:
                flash("Confirm your email before logging in.", "warning")
            else:
                login_user(user, remember=form.remember.data)
                ensure_current_site()
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
        else:
            flash("Invalid username or password.", "danger")

    return render_template(
        "login.html",
        form=form,
        settings=_settings_or_none(),
        platform_settings=_platform_settings_or_none(),
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    """Create a new public account, site, and email confirmation token."""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    platform_settings = PlatformSettings.get_or_create()
    if not platform_settings.allow_self_registration:
        flash("Self registration is disabled on this Piantala server.", "warning")
        return redirect(url_for("auth.login"))

    form = RegisterForm()
    if form.validate_on_submit():
        if not platform_settings.smtp_is_configured:
            flash("Registration email is not configured yet. Ask an administrator to complete SMTP settings.", "danger")
            return render_template("register.html", form=form, settings=_settings_or_none(), platform_settings=platform_settings)

        user = User(
            username=form.username.data,
            email=form.email.data,
            preferred_locale=form.preferred_locale.data,
            is_active=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()

        admin_role = Role.query.filter_by(name="admin").first()
        site = Site.create_with_unique_slug(form.site_name.data, owner=user)
        db.session.flush()
        db.session.add(SiteMembership(site=site, user=user, role=admin_role))
        db.session.add(GardenSettings(site=site, site_name=site.name))
        from .models import HomeAssistantSettings

        db.session.add(HomeAssistantSettings(site=site))
        token, raw_token = AuthToken.issue(
            purpose="confirm_registration",
            expires_in_hours=24,
            email=user.email,
            user=user,
            site=site,
        )
        db.session.flush()

        try:
            send_email(
                to_email=user.email or "",
                subject="Confirm your Piantala account",
                text_body=(
                    f"Hello {user.username},\n\n"
                    f"Confirm your Piantala account and activate your site '{site.name}' by opening this link:\n\n"
                    f"{_build_external_url('auth.confirm_registration', token=raw_token)}\n\n"
                    "If you did not request this account, you can ignore this email."
                ),
            )
        except MailError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("register.html", form=form, settings=_settings_or_none(), platform_settings=platform_settings)

        db.session.commit()
        flash("Account created. Check your email and confirm the registration link.", "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "register.html",
        form=form,
        settings=_settings_or_none(),
        platform_settings=platform_settings,
    )


@bp.route("/confirm-registration")
def confirm_registration():
    """Confirm one self-registration email token and activate the first site session."""
    raw_token = (request.args.get("token") or "").strip()
    token = AuthToken.consume(raw_token, purpose="confirm_registration") if raw_token else None
    if token is None or token.user is None:
        flash("This confirmation link is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))

    token.used_at = datetime.now(UTC)
    token.user.email_confirmed_at = datetime.now(UTC)
    login_user(token.user)
    if token.site is not None:
        set_current_site(token.site)
    token.user.last_login_at = datetime.now(UTC)
    db.session.commit()
    flash("Email confirmed. Welcome to your new Piantala site.", "success")
    return redirect(url_for("main.index"))


@bp.route("/accept-invite", methods=["GET", "POST"])
def accept_invite():
    """Accept one site invitation for an existing or new account."""
    raw_token = (request.values.get("token") or "").strip()
    token = AuthToken.consume(raw_token, purpose="site_invite") if raw_token else None
    if token is None or token.site is None or token.email is None:
        flash("This invitation link is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))

    if current_user.is_authenticated:
        if (current_user.email or "").casefold() != token.email.casefold():
            flash("Log in with the invited email address to accept this invitation.", "warning")
            return redirect(url_for("auth.login"))
        _membership_accept(token, current_user)
        db.session.commit()
        flash(f"You joined the site '{token.site.name}'.", "success")
        return redirect(url_for("main.index"))

    existing_user = User.query.filter_by(email=token.email.casefold()).first()
    if existing_user is not None:
        login_user(existing_user)
        _membership_accept(token, existing_user)
        existing_user.last_login_at = datetime.now(UTC)
        db.session.commit()
        flash(f"You joined the site '{token.site.name}'.", "success")
        return redirect(url_for("main.index"))

    form = InvitationRegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=(form.username.data or "").strip(),
            email=token.email.casefold(),
            preferred_locale=form.preferred_locale.data,
            is_active=True,
            email_confirmed_at=datetime.now(UTC),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        _membership_accept(token, user)
        login_user(user)
        user.last_login_at = datetime.now(UTC)
        db.session.commit()
        flash(f"Account created and site '{token.site.name}' joined.", "success")
        return redirect(url_for("main.index"))

    return render_template(
        "invite_accept.html",
        form=form,
        invite_token=token,
        settings=_settings_or_none(),
        platform_settings=_platform_settings_or_none(),
    )


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """End the current user session."""
    logout_user()
    clear_current_site()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Let a logged-in user update profile-level preferences."""
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


@bp.route("/sites/<int:site_id>/switch", methods=["POST"])
@login_required
def switch_site(site_id: int):
    """Switch the current authenticated session to another accessible site.

    Parameters:
        site_id: Identifier of the selected site.
    """
    site = Site.query.get_or_404(site_id)
    if not current_user.can_access_site(site):
        flash("You do not have access to that site.", "danger")
        return redirect(url_for("main.index"))
    set_current_site(site)
    flash(f"Current site changed to '{site.name}'.", "success")
    return redirect(request.form.get("next") or url_for("main.index"))
