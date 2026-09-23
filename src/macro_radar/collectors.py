from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from datetime import timezone
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .models import RawItem, SourceConfig, utcnow

LOGGER = logging.getLogger(__name__)
USER_AGENT = "MacroEventRadar/0.1 (+local research tool; respectful polling)"


def _html_text(response: httpx.Response) -> str:
    """Decode public pages that sometimes mislabel GB18030 pages as UTF-8."""
    candidates = []
    for encoding in (response.encoding, "utf-8", "gb18030", "big5"):
        if not encoding or encoding in {item[0] for item in candidates}:
            continue
        try:
            text = response.content.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
        candidates.append((encoding, text.count("\ufffd"), len(text), text))
    return min(candidates, key=lambda item: (item[1], -item[2]))[3] if candidates else response.text


def _date(value: str | None):
    if not value:
        return None
    try:
        # IAEA uses a compact YY-MM-DD format that dateutil otherwise reads as
        # DD-MM-YY for values such as "26-09-18".
        if re.match(r"^\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}$", value.strip()):
            return datetime.strptime(value.strip(), "%y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        compact = re.search(r"(20\d{2})(\d{2})(\d{2})", value)
        if compact:
            return datetime(int(compact.group(1)), int(compact.group(2)), int(compact.group(3)), tzinfo=timezone.utc)
        match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?", value)
        if match:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
        month_date = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})",
            value,
            re.IGNORECASE,
        )
        if month_date:
            return datetime.strptime(
                f"{month_date.group(1)} {month_date.group(2)} {month_date.group(3)}", "%B %d %Y"
            ).replace(tzinfo=timezone.utc)
        parsed = date_parser.parse(value)
        parsed = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
        # Feeds occasionally contain placeholder years (for example 9999) or
        # malformed future dates. Do not let those become the radar's latest
        # event timestamp; scheduled events are handled separately by the
        # pipeline and are not live news.
        if parsed.year < 2000 or parsed > utcnow() + timedelta(days=366):
            return None
        return parsed
    except (ValueError, TypeError, OverflowError):
        return None


def _id(source_id: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{source_id}|{url}|{title}".encode()).hexdigest()


class RSSCollector:
    def collect(self, source: SourceConfig, limit: int = 50) -> list[RawItem]:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20) as client:
            response = client.get(source.url)
            response.raise_for_status()
        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            raise RuntimeError(f"invalid feed: {feed.bozo_exception}")
        now = utcnow()
        items = []
        for entry in feed.entries[:limit]:
            title = BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True)
            url = entry.get("link", source.url)
            summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
            external_id = entry.get("id") or entry.get("guid") or _id(source.id, url, title)
            items.append(RawItem(
                source_id=source.id,
                source_name=source.name,
                external_id=str(external_id),
                title=title,
                url=url,
                published_at=_date(entry.get("published") or entry.get("updated")),
                fetched_at=now,
                summary=summary,
                raw={"tags": [tag.get("term") for tag in entry.get("tags", [])]},
            ))
        return items


class HTMLCollector:
    def collect(self, source: SourceConfig, limit: int = 50) -> list[RawItem]:
        selectors = source.selectors
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20) as client:
            response = client.get(source.url)
            response.raise_for_status()
        soup = BeautifulSoup(_html_text(response), "html.parser")
        now, items = utcnow(), []
        nodes = soup.select(selectors["item"]) if selectors.get("item") else soup.select("a[href]")
        include = [part.strip().lower() for part in selectors.get("link_contains", "").split(",") if part.strip()]
        seen = set()
        for node in nodes:
            if node.name == "a":
                title_node, link_node = node, node
            else:
                title_node = node.select_one(selectors.get("title", "a"))
                link_node = node.select_one(selectors.get("link", "a"))
            if not title_node or not link_node or not link_node.get("href"):
                continue
            title = title_node.get_text(" ", strip=True)
            url = urljoin(source.url, link_node["href"])
            if include and not any(term in url.lower() for term in include):
                continue
            normalized_title = re.sub(r"\s+", " ", title).strip().lower()
            skip_titles = {
                "skip to main content", "skip to content", "skip to main content (press enter).",
                "press releases", "view all press releases", "briefings & statements",
                "read more", "place holder", "advanced search",
            }
            if (
                url in seen
                or url.split("#", 1)[0].rstrip("/") == source.url.rstrip("/")
                or not url.startswith(("http://", "https://"))
                or normalized_title in skip_titles
                or normalized_title.startswith("skip to ")
                or len(title) < 12
                or len(title) > 300
            ):
                continue
            seen.add(url)
            date_node = node.select_one(selectors.get("date", "__never__"))
            summary_node = node.select_one(selectors.get("summary", "__never__"))
            context_node = node.find_parent("li") or node.find_parent("article") or (node.parent.parent if node.parent else None) or node.parent or node
            context = context_node.get_text(" ", strip=True)
            date_text = date_node.get("datetime") if date_node and date_node.get("datetime") else date_node.get_text(" ", strip=True) if date_node else context
            published_at = _date(date_text) or _date(url)
            items.append(RawItem(
                source_id=source.id,
                source_name=source.name,
                external_id=_id(source.id, url, title),
                title=title,
                url=url,
                published_at=published_at,
                fetched_at=now,
                summary=summary_node.get_text(" ", strip=True) if summary_node else "",
            ))
            if len(items) >= limit:
                break
        return items


def collect(source: SourceConfig, limit: int = 50) -> list[RawItem]:
    collectors = {"rss": RSSCollector(), "html": HTMLCollector()}
    if source.kind not in collectors:
        raise ValueError(f"unsupported source kind: {source.kind}")
    LOGGER.info("collecting source=%s kind=%s", source.id, source.kind)
    return collectors[source.kind].collect(source, limit)
