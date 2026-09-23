from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .config import load_sources, load_yaml
from .pipeline import run_pipeline
from .store import EventStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="macro-radar")
    result.add_argument("--sources", default="config/sources.yaml")
    result.add_argument("--rules", default="config/rules.yaml")
    result.add_argument("--db", default=os.getenv("RADAR_DB", "data/events.db"))
    result.add_argument("--limit", type=int, default=20)
    result.add_argument("--min-push-score", type=int, default=int(os.getenv("RADAR_MIN_PUSH_SCORE", "75")))
    result.add_argument("--max-push-age-hours", type=float, default=float(os.getenv("RADAR_MAX_PUSH_AGE_HOURS", "24")))
    result.add_argument("--webhook-url", default=os.getenv("RADAR_WEBHOOK_URL", ""))
    result.add_argument("--log-file", default=os.getenv("RADAR_LOG_FILE", ""))
    result.add_argument("--json", action="store_true", help="print new events as JSON lines")
    result.add_argument("--list", action="store_true", help="list stored events instead of collecting")
    result.add_argument("--min-score", type=int, default=0)
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=os.getenv("RADAR_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )
    store = EventStore(args.db)
    try:
        if args.list:
            print(json.dumps(store.latest(args.limit, args.min_score), ensure_ascii=False, indent=2))
            return 0
        sources = load_sources(Path(args.sources))
        rules = load_yaml(Path(args.rules))
        stats, events = run_pipeline(
            sources, rules, store, limit=args.limit, webhook_url=args.webhook_url,
            min_push_score=args.min_push_score, max_push_age_hours=args.max_push_age_hours,
        )
        if args.json:
            for event in events:
                print(json.dumps(event.to_dict(), ensure_ascii=False))
        print(json.dumps(stats.__dict__, ensure_ascii=False))
        return 0 if stats.sources_ok else 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
