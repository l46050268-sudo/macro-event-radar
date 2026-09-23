from datetime import datetime, timezone

from macro_radar.models import RawItem, SourceConfig
from macro_radar.collectors import _date
from macro_radar.normalize import canonical_url, entities, impacted_assets
from macro_radar.scoring import score_item


RULES = {
    "event_types": {"sanctions": {"weight": 32, "keywords": ["sanction", "ofac"]}},
    "impact_keywords": [{"keywords": ["ofac", "sanction"], "assets": ["USD", "CNH"]}],
    "critical_terms": ["effective immediately"],
}


def test_url_canonicalization():
    assert canonical_url("HTTPS://Example.com/a/?utm_source=x&b=2#top") == "https://example.com/a?b=2"


def test_entities_and_assets():
    text = "OFAC imposed sanctions involving China and Iran"
    assert {"US Treasury", "China", "Iran"}.issubset(entities(text))
    assert impacted_assets(text, RULES) == ["CNH", "USD"]


def test_official_critical_event_scores_high():
    source = SourceConfig("ofac", "OFAC", "rss", "https://example.com", trust_score=1.0)
    raw = RawItem("ofac", "OFAC", "1", "OFAC sanctions effective immediately", "https://example.com/1",
                  datetime.now(timezone.utc), datetime.now(timezone.utc))
    score, event_type, _ = score_item(raw, source, RULES)
    assert event_type == "sanctions"
    assert score >= 75


def test_compact_iaea_date_is_year_first():
    assert _date("26-09-18  06:00").isoformat() == "2026-09-18T06:00:00+00:00"


def test_source_name_does_not_force_event_classification():
    source = SourceConfig("ecb", "European Central Bank - Press and Speeches", "rss", "https://example.com")
    raw = RawItem("ecb", source.name, "1", "Consumer Expectations Survey results", "https://example.com/1",
                  datetime.now(timezone.utc), datetime.now(timezone.utc))
    _, event_type, _ = score_item(raw, source, {
        "event_types": {"policy_speech": {"weight": 16, "keywords": ["speech"]}},
        "impact_keywords": [], "critical_terms": [],
    })
    assert event_type == "other"


def test_market_gate_filters_humanitarian_updates_but_keeps_market_conflict():
    source = SourceConfig("un", "United Nations", "rss", "https://example.com")
    gate_rules = {
        "event_types": {
            "conflict": {"weight": 34, "keywords": ["attack", "conflict"]},
        },
        "impact_keywords": [],
        "critical_terms": [],
        "market_gate": {
            "allowed_event_types": ["conflict"],
            "market_signal_keywords": ["attack", "missile"],
            "market_conflict_keywords": ["missile"],
            "high_confidence_market_keywords": ["missile"],
            "exclude_if_no_market_signal": ["humanitarian", "human rights"],
        },
    }
    humanitarian = RawItem("un", "United Nations", "1", "Humanitarian aid and human rights update", "https://example.com/1", datetime.now(timezone.utc), datetime.now(timezone.utc))
    missile = RawItem("un", "United Nations", "2", "Missile attack disrupts shipping lane", "https://example.com/2", datetime.now(timezone.utc), datetime.now(timezone.utc))
    assert score_item(humanitarian, source, gate_rules)[2]["eligible"] is False
    assert score_item(missile, source, gate_rules)[2]["eligible"] is True


def test_market_gate_filters_generic_crypto_and_company_news():
    source = SourceConfig("market", "Public market feed", "rss", "https://example.com")
    gate_rules = {
        "event_types": {"energy_supply": {"weight": 29, "keywords": ["oil prices", "energy stocks"]}},
        "impact_keywords": [], "critical_terms": [],
        "market_gate": {
            "allowed_event_types": ["energy_supply"],
            "market_signal_keywords": ["oil prices", "energy stocks"],
            "market_conflict_keywords": [],
            "high_confidence_market_keywords": ["oil prices", "energy stocks"],
            "exclude_if_no_market_signal": [],
            "exclude_generic_market_noise": ["crypto", "earnings"],
        },
    }
    crypto = RawItem("market", source.name, "1", "Crypto stocks rally after earnings", "https://example.com/1", datetime.now(timezone.utc), datetime.now(timezone.utc))
    oil = RawItem("market", source.name, "2", "Oil prices jump after tanker disruption", "https://example.com/2", datetime.now(timezone.utc), datetime.now(timezone.utc))
    assert score_item(crypto, source, gate_rules)[2]["eligible"] is False
    assert score_item(oil, source, gate_rules)[2]["eligible"] is True
