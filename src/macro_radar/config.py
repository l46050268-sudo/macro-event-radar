from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import SourceConfig


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_sources(path: str | Path) -> list[SourceConfig]:
    data = load_yaml(path)
    sources = []
    for item in data.get("sources", []):
        sources.append(SourceConfig(**item))
    return sources
