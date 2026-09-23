from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SourceConfig:
    id: str
    name: str
    kind: str
    url: str
    enabled: bool = True
    authority: str = "official"
    topics: list[str] = field(default_factory=list)
    trust_score: float = 1.0
    selectors: dict[str, str] = field(default_factory=dict)
    poll_seconds: int = 300


@dataclass(slots=True)
class RawItem:
    source_id: str
    source_name: str
    external_id: str
    title: str
    url: str
    published_at: datetime | None
    fetched_at: datetime
    summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    event_id: str
    fingerprint: str
    source_id: str
    source_name: str
    title: str
    summary_zh: str
    original_summary: str
    url: str
    published_at: datetime
    fetched_at: datetime
    event_type: str
    importance: int
    severity: str
    entities: list[str]
    assets: list[str]
    topics: list[str]
    authority: str
    status: str = "new"

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        for key in ("published_at", "fetched_at"):
            result[key] = result[key].isoformat()
        return result
