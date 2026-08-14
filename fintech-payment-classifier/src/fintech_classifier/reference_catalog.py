"""Curated local company catalogue used before public web research.

This is intentionally a cache of *verified business facts*, not a second ML
model.  The only lookup key is a valid INN.  Records waiting for review can be
stored beside active records but are never returned to the runtime pipeline.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .research_store import ResearchStore
from .validation import valid_inn


ACTIVE_STATUS = "active"
PENDING_STATUS = "pending_manual_verification"
ALLOWED_CLASSES = {"A", "B", "NON_FINTECH"}


def normalise_catalog_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate the small, portable JSON contract used by catalogue imports."""
    value = dict(record)
    value["inn"] = str(value.get("inn") or "").strip()
    if not valid_inn(value["inn"]):
        raise ValueError(f"Invalid reference INN: {value['inn']!r}")
    value["reference_class"] = str(value.get("reference_class") or "").strip()
    if value["reference_class"] not in ALLOWED_CLASSES:
        raise ValueError("reference_class must be A, B or NON_FINTECH")
    value["legal_name"] = str(value.get("legal_name") or "").strip()
    value["official_website"] = str(value.get("official_website") or "").strip()
    parsed = urlparse(value["official_website"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid official website for {value['inn']}")
    value["official_domain"] = str(value.get("official_domain") or parsed.netloc).lower()
    if not value["legal_name"]:
        raise ValueError(f"Missing legal_name for {value['inn']}")
    if value.get("verification_status") not in {ACTIVE_STATUS, PENDING_STATUS, "rejected"}:
        raise ValueError("verification_status must be active, pending_manual_verification or rejected")
    for field in ("website_keywords", "website_keyphrases", "website_signals", "legal_sources", "website_sources", "aliases"):
        raw = value.get(field) or []
        if not isinstance(raw, list):
            raise ValueError(f"{field} must be a list")
        value[field] = raw
    return value


def active_reference(store: ResearchStore | None, inn: str | None) -> dict[str, Any] | None:
    """Load an activated reference record without mutating the research DB."""
    if store is None or not inn or not valid_inn(inn):
        return None
    return store.get_active_reference_company(inn)


def _keyword_item(text: str, score: float, index: int) -> dict[str, Any]:
    return {
        "keyword_type": "keyword", "text": text, "normalized_text": text.lower(),
        "score": float(score), "occurrences": 1, "page_urls": [], "contexts": [],
        "source": "curated_catalog", "rank": index,
    }


def _keyphrase_item(text: str, score: float, index: int) -> dict[str, Any]:
    return {
        "keyword_type": "keyphrase", "text": text, "normalized_text": text.lower(),
        "score": float(score), "occurrences": 1, "page_urls": [], "contexts": [],
        "source": "curated_catalog", "rank": index,
    }


def site_state_from_reference(record: dict[str, Any]) -> dict[str, Any]:
    """Adapt a cached record to the existing website-state contract.

    No request, crawler or HTML parser is run here.  ``success`` means that a
    previously verified local website profile is available, not that a network
    response was fetched during the current classification run.
    """
    website = str(record["official_website"])
    keywords = [_keyword_item(str(item), max(1.0, 20.0 - index), index)
                for index, item in enumerate(record.get("website_keywords") or [], 1)]
    keyphrases = [_keyphrase_item(str(item), max(1.0, 20.0 - index), index)
                  for index, item in enumerate(record.get("website_keyphrases") or [], 1)]
    evidence: list[dict[str, Any]] = []
    for raw in record.get("website_signals") or []:
        if not isinstance(raw, dict):
            continue
        evidence.append({
            "signal_family": raw.get("signal_family") or "CURATED_SITE_SIGNAL",
            "matched_phrase": raw.get("matched_phrase") or raw.get("phrase") or "",
            "context": raw.get("context") or "",
            "page_url": raw.get("page_url") or website,
            "html_zone": raw.get("html_zone") or "curated_profile",
            "weight": float(raw.get("weight") or 0.0),
        })
    candidate = {
        "candidate_url": website, "candidate_source": "проверенные сведения",
        "source_type": "curated_catalog", "domain_role": "OFFICIAL_CANDIDATE",
        "role_reason": "проверенный официальный домен", "brand_match": True,
        "title_match": True, "search_score": 100.0, "verification_score": 100.0,
        "candidate_score": 100.0, "candidate_status": "confirmed",
        "verification_status": "confirmed_by_website", "fetch_status": "success",
        "analysis_status": "success", "selected": True, "search_position": 1,
        "positive_evidence": ["локально проверенный официальный домен"],
        "negative_evidence": [], "checked_pages": [],
    }
    return {
        "site_url": website, "verification_status": "confirmed_by_website",
        "fetch_status": "success", "analysis_status": "success", "evidence": evidence,
        "site_keywords": keywords, "site_keyphrases": keyphrases,
        "website_search": {"attempts": [], "candidates": [candidate]},
    }


def reference_decision(record: dict[str, Any]) -> dict[str, Any]:
    """Produce an explicit deterministic decision for a curated record."""
    cls = str(record["reference_class"])
    probabilities = {key: (0.995 if key == cls else 0.0025) for key in ("A", "B", "NON_FINTECH")}
    return {
        "scores": probabilities, "final_class": cls, "original_final_class": cls,
        "decision_status": "AUTO", "final_confidence": 0.995, "score_gap": 0.9925,
        "hard_conflicts": [], "review_reasons": [],
    }
