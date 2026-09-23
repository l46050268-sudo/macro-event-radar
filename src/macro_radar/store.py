from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from .models import Event, RawItem, SourceConfig, utcnow
from .normalize import normalize, normalized_title
from .scoring import score_item


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  source_id TEXT NOT NULL DEFAULT '',
  source_name TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  summary_zh TEXT NOT NULL,
  original_summary TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  published_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  event_type TEXT NOT NULL,
  importance INTEGER NOT NULL,
  severity TEXT NOT NULL,
  entities_json TEXT NOT NULL,
  assets_json TEXT NOT NULL,
  topics_json TEXT NOT NULL,
  authority TEXT NOT NULL,
  market_relevant INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_score ON events(importance DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_url ON events(canonical_url);
CREATE TABLE IF NOT EXISTS sightings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  url TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  UNIQUE(event_id, source_id, url),
  FOREIGN KEY(event_id) REFERENCES events(event_id)
);
"""


def _tokens(value: str) -> set[str]:
    return set(normalized_title(value).split())


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


class EventStore:
    def __init__(self, path: str):
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Add fields introduced after the first MVP without losing existing data."""
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
        for name in ("source_id", "source_name"):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE events ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            self.connection.execute(f"UPDATE events SET {name}=COALESCE((SELECT {name} FROM sightings WHERE sightings.event_id=events.event_id ORDER BY id LIMIT 1),'') WHERE {name}=''")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
        if "market_relevant" not in columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN market_relevant INTEGER NOT NULL DEFAULT 1")
        self.connection.commit()

    def refresh_market_relevance(self, rules: dict):
        """Apply the market-only gate to rows saved by older versions."""
        rows = self.connection.execute(
            "SELECT event_id, source_id, source_name, title, original_summary, canonical_url FROM events"
        ).fetchall()
        for row in rows:
            raw = RawItem(
                source_id=row["source_id"], source_name=row["source_name"],
                external_id=row["event_id"], title=row["title"], url=row["canonical_url"],
                published_at=None, fetched_at=utcnow(), summary=row["original_summary"] or "",
            )
            source = SourceConfig(row["source_id"], row["source_name"], "unknown", row["canonical_url"])
            score, event_type, details = score_item(raw, source, rules)
            refreshed = normalize(raw, source, rules, score, event_type)
            self.connection.execute(
                """UPDATE events SET market_relevant=?, event_type=?, importance=?, severity=?,
                   entities_json=?, assets_json=?, summary_zh=? WHERE event_id=?""",
                (
                    1 if details.get("eligible", True) else 0, event_type, score, refreshed.severity,
                    json.dumps(refreshed.entities, ensure_ascii=False),
                    json.dumps(refreshed.assets, ensure_ascii=False),
                    refreshed.summary_zh, row["event_id"],
                ),
            )
        self.connection.commit()

    def close(self):
        self.connection.close()

    def _duplicate_id(self, event: Event) -> str | None:
        row = self.connection.execute(
            "SELECT event_id FROM events WHERE fingerprint=? OR canonical_url=? LIMIT 1",
            (event.fingerprint, event.url),
        ).fetchone()
        if row:
            return row["event_id"]
        candidates = self.connection.execute(
            "SELECT event_id, title FROM events WHERE published_at >= datetime('now', '-3 days') ORDER BY published_at DESC LIMIT 300"
        ).fetchall()
        for candidate in candidates:
            if _similarity(event.title, candidate["title"]) >= 0.82:
                return candidate["event_id"]
        return None

    def save(self, event: Event) -> tuple[str, bool]:
        duplicate_id = self._duplicate_id(event)
        event_id = duplicate_id or event.event_id
        if not duplicate_id:
            self.connection.execute(
                """INSERT INTO events (
                  event_id, fingerprint, source_id, source_name, title, normalized_title,
                  summary_zh, original_summary, canonical_url, published_at, fetched_at,
                  event_type, importance, severity, entities_json, assets_json, topics_json,
                  authority, market_relevant, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event.event_id, event.fingerprint, event.source_id, event.source_name,
                 event.title, normalized_title(event.title),
                 event.summary_zh, event.original_summary, event.url, event.published_at.isoformat(),
                 event.fetched_at.isoformat(), event.event_type, event.importance, event.severity,
                 json.dumps(event.entities, ensure_ascii=False), json.dumps(event.assets, ensure_ascii=False),
                 json.dumps(event.topics, ensure_ascii=False), event.authority, 1, event.status),
            )
        else:
            self.connection.execute(
                "UPDATE events SET source_id=?, source_name=? WHERE event_id=? AND (source_id='' OR source_name='')",
                (event.source_id, event.source_name, event_id),
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO sightings(event_id,source_id,source_name,url,seen_at) VALUES(?,?,?,?,?)",
            (event_id, event.source_id, event.source_name, event.url, event.fetched_at.isoformat()),
        )
        self.connection.commit()
        return event_id, duplicate_id is None

    def latest(self, limit: int = 20, min_score: int = 0) -> list[dict]:
        cutoff = (utcnow() + timedelta(hours=6)).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM events WHERE importance>=? AND market_relevant=1 AND published_at<=? ORDER BY published_at DESC LIMIT ?", (min_score, cutoff, limit)
        ).fetchall()
        return [dict(row) for row in rows]
