from __future__ import annotations

from flask import abort, g, session
from flask_login import current_user


def current_site_id() -> int | None:
    """Return the selected site id from request-local cache or session."""
    cached = getattr(g, "current_site_id", None)
    if cached is not None:
        return cached
    site_id = session.get("current_site_id")
    try:
        site_id = int(site_id) if site_id is not None else None
    except (TypeError, ValueError):
        site_id = None
    g.current_site_id = site_id
    return site_id


def current_site():
    """Return the selected site instance for the current request."""
    from .models import Site

    cached = getattr(g, "current_site", None)
    if cached is not None:
        return cached
    site_id = current_site_id()
    site = Site.query.get(site_id) if site_id is not None else None
    g.current_site = site
    return site


def set_current_site(site) -> None:
    """Persist the selected site for the current session.

    Parameters:
        site: Site instance to store as current.
    """
    session["current_site_id"] = site.id
    g.current_site = site
    g.current_site_id = site.id


def clear_current_site() -> None:
    """Remove the selected site from the current session."""
    session.pop("current_site_id", None)
    g.current_site = None
    g.current_site_id = None


def ensure_current_site():
    """Pick one accessible site for the logged-in user when none is selected."""
    if not getattr(current_user, "is_authenticated", False):
        clear_current_site()
        return None

    site = current_site()
    if site is not None and current_user.can_access_site(site):
        return site

    accessible_sites = current_user.accessible_sites
    if not accessible_sites:
        clear_current_site()
        return None

    site = accessible_sites[0]
    set_current_site(site)
    return site


def require_current_site():
    """Return the current site or abort when the user cannot access one."""
    site = ensure_current_site()
    if site is None:
        abort(403)
    return site
