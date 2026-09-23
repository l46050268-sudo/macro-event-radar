from __future__ import annotations

from datetime import datetime, timezone

from .models import RawItem, SourceConfig
from .normalize import classify, contains_term, entities, impacted_assets


def _matches(text: str, terms: list[str]) -> list[str]:
    matches = []
    for term in terms:
        if not term:
            continue
        if contains_term(text, term):
            matches.append(term)
    return matches


def _market_relevance(content_text: str, title_text: str, event_type: str, rules: dict) -> tuple[bool, list[str]]:
    """Keep only events with an identifiable market transmission channel."""
    gate = rules.get("market_gate") or {}
    if not gate:
        return True, ["market_gate_disabled"]

    allowed = set(gate.get("allowed_event_types", []))
    signal_matches = _matches(content_text, gate.get("market_signal_keywords", []))
    conflict_matches = _matches(content_text, gate.get("market_conflict_keywords", []))
    strong_matches = _matches(content_text, gate.get("high_confidence_market_keywords", []))
    excluded_matches = _matches(title_text, gate.get("exclude_if_no_market_signal", []))
    noise_matches = _matches(title_text, gate.get("exclude_generic_market_noise", []))
    hard_noise_matches = _matches(title_text, gate.get("hard_exclude_generic_market_noise", []))
    strong_title_matches = _matches(title_text, gate.get("high_confidence_market_keywords", []))
    reasons = []

    if event_type not in allowed:
        reasons.append("event_type_not_market_relevant")
    if not signal_matches:
        reasons.append("no_market_signal")
    if event_type == "conflict" and not conflict_matches:
        reasons.append("conflict_without_financial_transmission")
    if event_type in {"rate_decision", "sanctions", "export_control", "tariff_trade", "conflict", "nuclear", "energy_supply", "major_policy", "macro_data", "policy_speech"} and not strong_matches:
        reasons.append("no_concrete_market_trigger")
    if excluded_matches and not strong_title_matches:
        reasons.append("general_humanitarian_or_rights_topic")
    if hard_noise_matches or (noise_matches and not strong_title_matches):
        reasons.append("generic_market_noise")

    eligible = not reasons
    return eligible, reasons or ["market_signal=" + ",".join(signal_matches[:4])]


def score_item(raw: RawItem, source: SourceConfig, rules: dict) -> tuple[int, str, dict]:
    content_text = f"{raw.title} {raw.summary}".lower()
    context_text = f"{source.name} {content_text}".lower()
    event_type, event_weight = classify(content_text, rules)
    market_relevant, market_reasons = _market_relevance(content_text, raw.title.lower(), event_type, rules)
    score = 10 + round(source.trust_score * 18) + event_weight
    reasons = [f"source_trust={source.trust_score:.2f}", f"event_type={event_type}"]
    reasons.extend(market_reasons)

    if source.authority == "official":
        score += 8
        reasons.append("official_source")
    critical = [term for term in rules.get("critical_terms", []) if term.lower() in content_text]
    if critical:
        score += min(15, 5 * len(critical))
        reasons.append("critical_terms=" + ",".join(critical[:3]))
    entity_list = entities(context_text)
    assets = impacted_assets(context_text, rules)
    score += min(8, len(entity_list) * 2)
    score += min(8, len(assets))
    if raw.published_at:
        age_hours = max(0, (datetime.now(timezone.utc) - raw.published_at).total_seconds() / 3600)
        if age_hours <= 2:
            score += 6
            reasons.append("fresh_under_2h")
        elif age_hours <= 24:
            score += 3
            reasons.append("fresh_under_24h")
    return min(100, score), event_type, {
        "reasons": reasons,
        "entities": entity_list,
        "assets": assets,
        "eligible": market_relevant,
    }
