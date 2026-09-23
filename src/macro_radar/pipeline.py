from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .collectors import collect
from .models import Event, SourceConfig
from .normalize import normalize
from .notify import send_webhook
from .scoring import score_item
from .store import EventStore

LOGGER = logging.getLogger(__name__)


@dataclass
class RunStats:
    sources_ok: int = 0
    sources_failed: int = 0
    sources_skipped: int = 0
    scheduled: int = 0
    fetched: int = 0
    filtered: int = 0
    inserted: int = 0
    duplicates: int = 0
    pushed: int = 0
    health: list = field(default_factory=list)


def run_pipeline(sources: list[SourceConfig], rules: dict, store: EventStore, *, limit: int = 50,
                 webhook_url: str = "", min_push_score: int = 75,
                 max_push_age_hours: float = 24,
                 previous_health: dict[str, dict] | None = None,
                 force: bool = False) -> tuple[RunStats, list[Event]]:
    stats, new_events = RunStats(), []
    enabled_sources = [source for source in sources if source.enabled]

    # Network collection is independent per source. Fetching sequentially
    # made one slow official page delay the whole refresh and could make the
    # next timer tick look as if it had produced no update. Keep SQLite writes
    # below in the main thread, but collect the public pages concurrently.
    def collect_one(source: SourceConfig):
        previous = (previous_health or {}).get(source.id) or {}
        if not force and source.poll_seconds > 0 and previous.get("checked"):
            try:
                checked = datetime.fromisoformat(previous["checked"])
                age = (datetime.now(timezone.utc) - checked).total_seconds()
                if age < source.poll_seconds:
                    health = dict(previous)
                    health["state"] = "跳过（等待轮询间隔）"
                    health["source_id"] = source.id
                    return source, [], health, None, True
            except (TypeError, ValueError):
                pass
        try:
            items = collect(source, limit=limit)
            cutoff = datetime.now(timezone.utc) + timedelta(hours=6)
            dates = [r.published_at for r in items if r.published_at and r.published_at <= cutoff]
            return source, items, {'source_id': source.id, 'name': source.name, 'checked': datetime.now(timezone.utc).isoformat(), 'latest': max(dates).isoformat() if dates else '', 'count': len(items), 'state': '成功' if items else '空结果，请检查解析', 'error': '', 'url': source.url}, None, False
        except Exception as exc:
            message = f'{type(exc).__name__}: {str(exc).strip()}'[:240]
            LOGGER.exception("source failed source=%s", source.id)
            return source, [], {'source_id': source.id, 'name': source.name, 'checked': datetime.now(timezone.utc).isoformat(), 'latest': '', 'count': 0, 'state': '失败', 'error': message, 'url': source.url}, exc, False

    collected = {}
    worker_count = min(16, max(1, len(enabled_sources)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="source") as executor:
        futures = [executor.submit(collect_one, source) for source in enabled_sources]
        for future in as_completed(futures):
            source, items, health, error, skipped = future.result()
            collected[source.id] = (source, items, health, error, skipped)

    # Preserve configured source order in the status panel and deterministic
    # event stream, while retaining the faster network phase.
    for source in enabled_sources:
        source, items, health, error, skipped = collected[source.id]
        stats.health.append(health)
        if skipped:
            stats.sources_skipped += 1
            continue
        if error:
            stats.sources_failed += 1
            continue
        stats.sources_ok += 1
        stats.fetched += len(items)
        for raw in items:
            if raw.published_at and raw.published_at > datetime.now(timezone.utc) + timedelta(hours=6):
                stats.scheduled += 1
                continue
            score, event_type, details = score_item(raw, source, rules)
            if not details.get('eligible', True):
                stats.filtered += 1
                continue
            event = normalize(raw, source, rules, score, event_type)
            _, created = store.save(event)
            if not created:
                stats.duplicates += 1
                continue
            stats.inserted += 1
            new_events.append(event)
            age_hours = max(0, (datetime.now(timezone.utc) - event.published_at).total_seconds() / 3600)
            if webhook_url and event.importance >= min_push_score and age_hours <= max_push_age_hours:
                try:
                    send_webhook(event, webhook_url)
                    stats.pushed += 1
                except Exception:
                    LOGGER.exception("webhook failed event=%s", event.event_id)
    return stats, sorted(new_events, key=lambda item: item.importance, reverse=True)
