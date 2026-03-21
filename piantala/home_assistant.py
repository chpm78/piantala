from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import datetime, UTC
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
    normalized = base_url.rstrip("/") + "/"
    return parse.urljoin(normalized, path.lstrip("/"))


def _ssl_context(verify_ssl: bool):
    if verify_ssl:
        return None
    return ssl._create_unverified_context()


def _api_request(settings: HomeAssistantSettings, path: str):
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
    payload = _api_request(settings, "/api/")
    if isinstance(payload, dict) and "message" in payload:
        return str(payload["message"])
    return "Connection successful."


def fetch_states(settings: HomeAssistantSettings) -> list[HomeAssistantState]:
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


def sync_entity_catalog(settings: HomeAssistantSettings) -> int:
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
