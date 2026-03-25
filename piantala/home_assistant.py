from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import datetime, UTC, timedelta
from urllib import error, parse, request

from .extensions import db
from .models import HomeAssistantEntityCatalog, HomeAssistantSettings


class HomeAssistantError(Exception):
    pass


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Piantala/0.1"
)


@dataclass
class HomeAssistantState:
    entity_id: str
    domain: str
    friendly_name: str | None
    state: str | None
    unit_of_measurement: str | None
    icon: str | None
    device_class: str | None
    last_updated: str | None
    attributes: dict


def _build_url(base_url: str, path: str) -> str:
    """Join a Home Assistant base URL and API path safely.

    Parameters:
        base_url: Root URL configured for Home Assistant.
        path: API path that should be resolved against the base URL.
    """
    normalized = base_url.rstrip("/") + "/"
    return parse.urljoin(normalized, path.lstrip("/"))


def _ssl_context(verify_ssl: bool):
    """Return an SSL context matching the configured certificate policy.

    Parameters:
        verify_ssl: Whether HTTPS certificates should be validated.
    """
    if verify_ssl:
        return None
    return ssl._create_unverified_context()


def _api_request(settings: HomeAssistantSettings, path: str):
    """Perform one authenticated Home Assistant API request.

    Parameters:
        settings: Saved Home Assistant connection settings.
        path: API path to request from the Home Assistant server.
    """
    if not settings.is_configured:
        raise HomeAssistantError("Home Assistant is not configured yet.")

    url = _build_url(settings.effective_url or "", path)
    req = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": settings.user_agent or DEFAULT_USER_AGENT,
        },
    )

    try:
        with request.urlopen(
            req,
            timeout=settings.request_timeout or 10,
            context=_ssl_context(settings.verify_ssl),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        parsed_detail = None
        try:
            parsed_detail = json.loads(detail) if detail else None
        except json.JSONDecodeError:
            parsed_detail = None

        if isinstance(parsed_detail, dict) and parsed_detail.get("cloudflare_error"):
            error_name = parsed_detail.get("error_name") or "Cloudflare blocked the request"
            owner_action = parsed_detail.get("owner_action_required")
            guidance = (
                "This request is being blocked by Cloudflare before it reaches Home Assistant. "
                "Use a direct/internal Home Assistant URL if possible, or relax the Cloudflare/WAF rule "
                "for this client and its User-Agent."
            )
            if owner_action:
                guidance += " The current Cloudflare response says the site owner must change the rule."
            raise HomeAssistantError(
                f"{error_name}. {guidance}"
            ) from exc

        raise HomeAssistantError(
            f"Home Assistant returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise HomeAssistantError(f"Could not reach Home Assistant: {exc.reason}") from exc


def test_connection(settings: HomeAssistantSettings) -> str:
    """Call the Home Assistant root API endpoint and return its status text.

    Parameters:
        settings: Saved Home Assistant connection settings.
    """
    payload = _api_request(settings, "/api/")
    if isinstance(payload, dict) and "message" in payload:
        return str(payload["message"])
    return "Connection successful."


def fetch_states(settings: HomeAssistantSettings) -> list[HomeAssistantState]:
    """Fetch entity states from Home Assistant and normalize them for Piantala.

    Parameters:
        settings: Saved Home Assistant connection settings.
    """
    payload = _api_request(settings, "/api/states")
    if not isinstance(payload, list):
        raise HomeAssistantError("Unexpected Home Assistant response from /api/states.")

    states: list[HomeAssistantState] = []
    for item in payload:
        entity_id = item.get("entity_id")
        if not entity_id or "." not in entity_id:
            continue

        attributes = item.get("attributes") or {}
        states.append(
            HomeAssistantState(
                entity_id=entity_id,
                domain=entity_id.split(".", 1)[0],
                friendly_name=attributes.get("friendly_name"),
                state=item.get("state"),
                unit_of_measurement=attributes.get("unit_of_measurement"),
                icon=attributes.get("icon"),
                device_class=attributes.get("device_class"),
                last_updated=item.get("last_updated"),
                attributes=attributes,
            )
        )

    return states


def fetch_entity_history(
    settings: HomeAssistantSettings,
    entity_ids: list[str],
    *,
    days: int,
) -> dict[str, list[dict[str, str | None]]]:
    """Fetch Home Assistant history samples for one or more entities.

    Parameters:
        settings: Saved Home Assistant connection settings.
        entity_ids: Entity ids whose history should be retrieved.
        days: Number of days to include in the requested history window.
    """
    normalized_ids = [entity_id for entity_id in entity_ids if entity_id]
    if not normalized_ids:
        return {}

    end_at = datetime.now(UTC)
    start_at = end_at - timedelta(days=days)
    history_path = (
        f"/api/history/period/{start_at.isoformat()}?"
        f"filter_entity_id={parse.quote(','.join(normalized_ids), safe=',.')}"
        f"&end_time={parse.quote(end_at.isoformat(), safe=':')}"
        "&minimal_response&no_attributes"
    )
    payload = _api_request(settings, history_path)
    if not isinstance(payload, list):
        raise HomeAssistantError("Unexpected Home Assistant response from /api/history/period.")

    history_by_entity: dict[str, list[dict[str, str | None]]] = {}
    for index, entity_history in enumerate(payload):
        if not isinstance(entity_history, list) or not entity_history:
            continue

        series_entity_id = None
        first_row = entity_history[0]
        if isinstance(first_row, dict):
            series_entity_id = first_row.get("entity_id")
        if not series_entity_id and index < len(normalized_ids):
            series_entity_id = normalized_ids[index]
        if not series_entity_id:
            continue

        points: list[dict[str, str | None]] = []
        for row in entity_history:
            if not isinstance(row, dict):
                continue
            points.append(
                {
                    "last_changed": row.get("last_changed"),
                    "state": row.get("state"),
                }
            )

        history_by_entity[series_entity_id] = points

    return history_by_entity


def sync_entity_catalog(settings: HomeAssistantSettings) -> int:
    """Refresh the local Home Assistant entity catalog from the remote server.

    Parameters:
        settings: Saved Home Assistant connection settings.
    """
    states = fetch_states(settings)
    now = datetime.now(UTC)

    existing = {
        row.entity_id: row
        for row in HomeAssistantEntityCatalog.query.all()
    }
    seen_ids: set[str] = set()

    for state in states:
        seen_ids.add(state.entity_id)
        row = existing.get(state.entity_id)
        if row is None:
            row = HomeAssistantEntityCatalog(entity_id=state.entity_id, domain=state.domain)
            db.session.add(row)

        row.domain = state.domain
        row.friendly_name = state.friendly_name
        row.state = state.state
        row.unit_of_measurement = state.unit_of_measurement
        row.icon = state.icon
        row.device_class = state.device_class
        row.last_updated = state.last_updated
        row.raw_attributes_json = json.dumps(state.attributes, sort_keys=True)
        row.seen_at = now

    stale_rows = (
        HomeAssistantEntityCatalog.query.filter(
            HomeAssistantEntityCatalog.entity_id.notin_(list(seen_ids))
        ).all()
        if seen_ids
        else HomeAssistantEntityCatalog.query.all()
    )
    for row in stale_rows:
        db.session.delete(row)

    settings.last_sync_at = now
    settings.last_error = None
    db.session.commit()
    return len(states)
