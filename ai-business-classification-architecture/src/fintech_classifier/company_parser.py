"""Stage 1: turn payment operations into unique legal-entity lookup requests.

This module deliberately does not classify a company and does not guess its web
site. Its output is an auditable queue for an official registry lookup by INN.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .schemas import PaymentOperation
from .validation import valid_inn

FNS_EGRUL_SEARCH_URL = "https://egrul.nalog.ru/index.html"


@dataclass
class CompanyLookupRequest:
    lookup_id: str
    inn: str | None
    legal_name_candidates: list[str]
    account_candidates: list[str]
    operation_ids: list[str]
    source_sides: list[str]
    lookup_status: str
    search_value: str | None
    registry_url: str = FNS_EGRUL_SEARCH_URL
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lookup_id": self.lookup_id, "inn": self.inn,
            "legal_name_candidates": self.legal_name_candidates,
            "account_candidates": self.account_candidates,
            "operation_ids": self.operation_ids, "source_sides": self.source_sides,
            "lookup_status": self.lookup_status, "search_value": self.search_value,
            "registry_url": self.registry_url, "warnings": self.warnings,
        }


def parse_company_lookup_requests(operations: list[PaymentOperation]) -> list[CompanyLookupRequest]:
    """Extract both sides of each payment into a deduplicated INN-first queue."""
    buckets: dict[str, dict] = defaultdict(lambda: {
        "inn": None, "names": set(), "accounts": set(), "operation_ids": set(),
        "sides": set(), "warnings": set(),
    })
    for operation in operations:
        for side in ("payer", "recipient"):
            inn = getattr(operation, f"{side}_inn")
            name = getattr(operation, f"{side}_name_normalized") or getattr(operation, f"{side}_name_raw")
            account = getattr(operation, f"{side}_account")
            if not inn and not name and not account:
                continue
            # A missing/invalid INN must not silently merge different companies.
            key = f"inn:{inn}" if valid_inn(inn) else f"manual:{account or ''}:{name or ''}:{operation.operation_id}:{side}"
            bucket = buckets[key]
            bucket["inn"] = inn if valid_inn(inn) else None
            if name:
                bucket["names"].add(str(name))
            if account:
                bucket["accounts"].add(str(account))
            bucket["operation_ids"].add(operation.operation_id)
            bucket["sides"].add(side)
            if inn and not valid_inn(inn):
                bucket["warnings"].add("invalid_inn: manual review required")
            if not inn:
                bucket["warnings"].add("missing_inn: manual review required")

    requests: list[CompanyLookupRequest] = []
    for index, (_, bucket) in enumerate(sorted(buckets.items()), 1):
        inn = bucket["inn"]
        names = sorted(bucket["names"])
        requests.append(CompanyLookupRequest(
            lookup_id=f"LOOKUP-{index:04d}", inn=inn, legal_name_candidates=names,
            account_candidates=sorted(bucket["accounts"]), operation_ids=sorted(bucket["operation_ids"]),
            source_sides=sorted(bucket["sides"]),
            lookup_status="ready_for_fns_lookup" if inn else "manual_identity_review",
            search_value=inn or (names[0] if names else None), warnings=sorted(bucket["warnings"]),
        ))
    return requests
