"""Central configuration for CVS Radar.

The values mirror PRD §14 and are intentionally plain dictionaries so a
future YAML/JSON loader can replace them without changing call sites.
"""

from __future__ import annotations

BRANDS: dict[str, list[str]] = {
    "7-11": ["7-11", "711", "7-eleven", "小7", "小七", "seven", "統一超"],
    "全家": ["全家", "FamilyMart", "family mart", "fami"],
    "萊爾富": ["萊爾富", "Hi-Life", "hilife"],
    "OK": ["OK超商", "OKmart", "OK"],
    "美聯社": ["美聯社"],
    "其他": [],
}

CRAWL = {
    "base_url": "https://www.ptt.cc",
    "board": "CVS",
    "max_pages": 5,
    "request_delay_sec": 1.0,
    "timeout_sec": 10,
    "retries": 3,
    "user_agent": "CVS-Radar/0.2 (+https://github.com/local/cvs-radar)",
    "cache_path": ".cvs_radar_seen.json",
}

SENTIMENT = {
    "backend": "lexicon",
    "tag_prior_weight": 0.6,
}

SCORING = {
    "role_weight": {"author": 1.5, "commenter": 1.0},
    "prior_mean": 0.5,
    "prior_strength": 3.0,
    "time_decay_lambda": 0.0,
    "per_user_cap": True,
    "exclude_self_push": True,
}

SUSPICION = {
    "min_activity": 5,
    "weight_floor": 0.1,
    "feature_weights": {
        "one_sided": 0.4,
        "single_brand": 0.25,
        "extreme": 0.25,
        "repeated_text": 0.10,
    },
}

CONSENSUS = {
    "n_eff_min": 3.0,
    "high_mean": 0.70,
    "low_mean": 0.40,
    "low_std": 0.15,
    "high_std": 0.25,
}

CONFIDENCE_BANDS = [
    (3.0, "低"),
    (8.0, "中"),
]

PRIVACY = {
    "hash_salt": "cvs-radar-local-v0",
    "public_include_contributors": False,
}
