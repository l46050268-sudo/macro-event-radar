from __future__ import annotations

import logging

import httpx

from .models import Event

LOGGER = logging.getLogger(__name__)


def webhook_payload(event: Event) -> dict:
    return {
        "type": "macro_event",
        "severity": event.severity,
        "score": event.importance,
        "title": event.title,
        "summary_zh": event.summary_zh,
        "event_type": event.event_type,
        "entities": event.entities,
        "assets": event.assets,
        "published_at": event.published_at.isoformat(),
        "source": event.source_name,
        "url": event.url,
    }


def send_webhook(event: Event, webhook_url: str) -> None:
    with httpx.Client(timeout=10) as client:
        response = client.post(webhook_url, json=webhook_payload(event))
        response.raise_for_status()
    LOGGER.info("pushed event=%s score=%s", event.event_id, event.importance)
