from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Event, RawItem, SourceConfig

ENTITY_ALIASES = {
    "Federal Reserve": ["federal reserve", "fomc", "fed chair", "powell"],
    "ECB": ["european central bank", "ecb", "lagarde"],
    "BOJ": ["bank of japan", "boj", "植田和男", "日本银行"],
    "PBOC": ["people's bank of china", "pboc", "中国人民银行", "央行"],
    "US Treasury": ["u.s. treasury", "us treasury", "department of the treasury", "ofac"],
    "OPEC+": ["opec+", "opec plus", "opec"],
    "IAEA": ["international atomic energy agency", "iaea", "国际原子能机构"],
    "China": ["china", "chinese", "中国"],
    "United States": ["united states", "u.s.", "american", "美国"],
    "Russia": ["russia", "russian", "俄罗斯"],
    "Ukraine": ["ukraine", "ukrainian", "乌克兰"],
    "Iran": ["iran", "iranian", "伊朗"],
    "Israel": ["israel", "israeli", "以色列"],
}


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalized_title(title: str) -> str:
    title = clean_text(title).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", title).strip()


def contains_term(text: str, term: str) -> bool:
    term = (term or "").lower()
    if not term:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in term):
        return term in text
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def fingerprint(title: str) -> str:
    return hashlib.sha256(normalized_title(title).encode()).hexdigest()


def entities(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(name for name, aliases in ENTITY_ALIASES.items() if any(alias.lower() in lowered for alias in aliases))


def classify(text: str, rules: dict) -> tuple[str, int]:
    lowered = text.lower()
    matches = []
    for event_type, rule in rules.get("event_types", {}).items():
        count = sum(1 for term in rule.get("keywords", []) if contains_term(lowered, term))
        if count:
            matches.append((int(rule.get("weight", 0)) + min(8, (count - 1) * 2), event_type))
    weight, event_type = max(matches, default=(8, "other"))
    return event_type, weight


def impacted_assets(text: str, rules: dict) -> list[str]:
    lowered = text.lower()
    result = set()
    for mapping in rules.get("impact_keywords", []):
        if any(contains_term(lowered, term) for term in mapping.get("keywords", [])):
            result.update(mapping.get("assets", []))
    return sorted(result)


def summary_zh(title: str, event_type: str, entity_list: list[str], assets: list[str]) -> str:
    labels = {
        "rate_decision": "央行决议",
        "sanctions": "制裁行动",
        "export_control": "出口管制",
        "tariff_trade": "关税与贸易政策",
        "conflict": "地缘冲突",
        "nuclear": "核问题",
        "energy_supply": "能源供应",
        "policy_speech": "重要讲话",
        "major_policy": "重大政策",
        "macro_data": "重大宏观数据",
        "other": "官方动态",
    }
    who = "、".join(entity_list[:4]) or "相关机构"
    affected = "、".join(assets[:6]) or "待评估"
    return f"【{labels.get(event_type, '官方动态')}】{who}：{title}。潜在影响资产：{affected}。"


def normalize(raw: RawItem, source: SourceConfig, rules: dict, score: int, event_type: str) -> Event:
    title = clean_text(raw.title)
    full_text = clean_text(f"{source.name} {title} {raw.summary}")
    entity_list = entities(full_text)
    assets = impacted_assets(full_text, rules)
    url = canonical_url(raw.url)
    fp = fingerprint(title)
    published = raw.published_at or raw.fetched_at
    event_id = hashlib.sha256(f"{fp}|{published.date().isoformat()}".encode()).hexdigest()[:24]
    severity = "critical" if score >= 90 else "high" if score >= 75 else "medium" if score >= 50 else "low"
    return Event(
        event_id=event_id, fingerprint=fp, source_id=source.id, source_name=source.name,
        title=title, summary_zh=summary_zh(title, event_type, entity_list, assets),
        original_summary=clean_text(raw.summary), url=url, published_at=published,
        fetched_at=raw.fetched_at, event_type=event_type, importance=score,
        severity=severity, entities=entity_list, assets=assets, topics=source.topics,
        authority=source.authority,
    )
