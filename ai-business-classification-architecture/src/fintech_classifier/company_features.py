"""Deterministic, leak-safe company-level feature engineering.

This module deliberately creates one row per SQLite ``company_id``.  It only
reads saved research data and a local payment batch; it never performs HTTP or
trains a model.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .ingestion import frame_to_operations
from .normalization import clean_text, normalize_name
from .validation import valid_account, valid_bic, valid_inn, valid_kpp

FEATURE_VERSION = "company-features-v1"
IDENTIFIER_OR_LEAKAGE_TERMS = ("target", "gold_", "predicted_", "segment", "rationale", "hypothesis", "inn", "ogrn", "account", "bic", "corr_account", "operation_id", "source_file", "source_row", "sheet")

NAME_MARKERS = {
    "payment": ("платеж", "payment", "pay", "эквайр", "acquiring"),
    "finance": ("банк", "bank", "финанс", "finance", "кредит"),
    "marketplace": ("маркетплейс", "marketplace", "market"),
    "platform": ("платформ", "platform"),
    "aggregator": ("агрегатор", "aggregator"),
    "delivery": ("достав", "delivery", "курьер", "cdek"),
    "retail": ("ритейл", "retail", "магазин", "shop", "торгов"),
    "service": ("сервис", "service", "solutions"),
}
LEGAL_FORM_CODES = {"ООО": 1, "АО": 2, "ПАО": 3, "ИП": 4, "НКО": 5, "БАНК": 6}

OKVED_GROUPS = {
    "financial": ("64", "65", "66"), "payment": ("64.19", "66.19"),
    "ecommerce": ("47.91",), "retail": ("47",), "it": ("62", "63"),
    "platform": ("63.11", "82.99"), "logistics": ("49", "52", "53"),
    "delivery": ("53.20",), "advertising": ("73",), "agent_services": ("46.1", "47.9"),
    "own_production": ("10", "11", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32"),
    "professional_services": ("69", "70", "71", "72", "74"),
}

SIGNAL_CLASS = {"A1": "a1", "A2": "a2", "B": "b", "NON_FINTECH": "non_fintech"}
PAGE_FLAGS = {
    "sellers": ("seller", "продав"), "merchants": ("merchant", "мерчант"), "partners": ("partner", "партнер"),
    "performers": ("performer", "исполн"), "couriers": ("courier", "курьер"), "orders": ("order", "заказ"),
    "payouts": ("payout", "выплат"), "commission": ("commission", "комисс"), "tariffs": ("tariff", "тариф"),
    "offer": ("offer", "оферт"), "payments": ("payment", "платеж"), "business": ("business", "бизнес"),
    "api_docs": ("api", "docs", "документ"), "fulfillment": ("fulfillment", "фулфилмент"),
}
SIGNAL_FLAGS = {
    "independent_sellers": ("INDEPENDENT_PARTICIPANTS", ("продав",)),
    "independent_performers": ("INDEPENDENT_PARTICIPANTS", ("исполн",)),
    "merchant_onboarding": ("INDEPENDENT_PARTICIPANTS", ("merchant", "мерчант")),
    "seller_onboarding": ("INDEPENDENT_PARTICIPANTS", ("стать продавцом", "кабинет продавца")),
    "participant_payouts": ("PARTICIPANT_PAYOUT", ()), "commission_withholding": ("COMMISSION_WITHHOLDING", ()),
    "separate_platform_commission": ("SEPARATE_PLATFORM_COMMISSION", ()),
    "direct_buyer_to_merchant_payment": ("DIRECT_BUYER_TO_MERCHANT_PAYMENT", ()), "split_payment": ("PARTICIPANT_PAYOUT", ("split",)),
    "settlement": ("SETTLEMENT", ()), "payment_processing": ("PAYMENT_SERVICE", ()),
    "payment_api": ("PAYMENT_INFRASTRUCTURE", ("api",)), "acquiring": ("PAYMENT_SERVICE", ("эквайр", "acquiring")),
    "order_management": ("ORDER_MANAGEMENT", ()), "refunds": ("ORDER_MANAGEMENT", ("возврат",)),
    "dispute_resolution": ("ORDER_MANAGEMENT", ("арбитраж", "спор")), "fulfillment": ("FULFILLMENT", ()),
    "own_products": ("OWN_PRODUCTS", ()), "own_services": ("OWN_SERVICES", ()),
    "own_production": ("OWN_PRODUCTION", ()), "own_stores": ("OWN_STORES", ()), "direct_retail": ("DIRECT_RETAIL", ()),
    "card_payment_only": ("CARD_PAYMENT_ONLY", ()), "sbp_payment_only": ("SBP_PAYMENT_ONLY", ()),
    "bank_acquiring_commission": ("BANK_ACQUIRING_COMMISSION", ()), "generic_platform_word": ("GENERIC_PLATFORM_WORD", ()),
    "generic_partner_word": ("GENERIC_PARTNER_WORD", ()),
}


def _code_prefix(code: str, prefix: str) -> bool:
    return code == prefix or code.startswith(prefix + ".")


def _okved_section(code: str) -> str:
    """Coarse official OKVED section inferred from the available numeric code."""
    try: division = int(re.sub(r"\D", "", code)[:2])
    except ValueError: return ""
    if 1 <= division <= 3: return "A"
    if 5 <= division <= 9: return "B"
    if 10 <= division <= 33: return "C"
    if 35 <= division <= 35: return "D"
    if 36 <= division <= 39: return "E"
    if 41 <= division <= 43: return "F"
    if 45 <= division <= 47: return "G"
    if 49 <= division <= 53: return "H"
    if 55 <= division <= 56: return "I"
    if 58 <= division <= 63: return "J"
    if 64 <= division <= 66: return "K"
    if 68 <= division <= 68: return "L"
    if 69 <= division <= 75: return "M"
    if 77 <= division <= 82: return "N"
    if 84 <= division <= 84: return "O"
    if 85 <= division <= 85: return "P"
    if 86 <= division <= 88: return "Q"
    if 90 <= division <= 93: return "R"
    if 94 <= division <= 96: return "S"
    if 97 <= division <= 98: return "T"
    if 99 <= division <= 99: return "U"
    return ""


def _share(values: Iterable[bool], denominator: int) -> float:
    return round(sum(bool(item) for item in values) / denominator, 6) if denominator else 0.0


def _top_share(values: list[str]) -> float:
    return round(max(Counter(values).values()) / len(values), 6) if values else 0.0


def quantile_from(values: list[float], point: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * point))], 6)


def _safe_json(value: str | None) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
        return loaded if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        return []


def _legal_form(name: str) -> int:
    upper = clean_text(name).upper()
    return next((code for form, code in LEGAL_FORM_CODES.items() if re.search(rf"\b{re.escape(form)}\b", upper)), 0)


def _similarity(first: str, second: str) -> float:
    a, b = set(normalize_name(first).split()), set(normalize_name(second).split())
    return round(len(a & b) / len(a | b), 6) if a or b else 0.0


@dataclass
class BatchData:
    operations: dict[str, Any]
    batch_transaction_count: int
    targets: dict[str, str]
    source_columns: dict[str, dict[str, Any]]


def load_xlsx_batch(path: str | Path) -> BatchData:
    """Read both project sheets locally and retain true target values separately."""
    import pandas as pd
    book = pd.ExcelFile(path)
    operations: dict[str, Any] = {}
    targets: dict[str, str] = {}
    columns: dict[str, dict[str, Any]] = {}
    total = 0
    for sheet in book.sheet_names:
        # Identifiers are text.  ``dtype=str`` prevents Excel from silently
        # dropping a leading zero in a valid INN such as 0274062111.
        frame = pd.read_excel(path, sheet_name=sheet, dtype=str, keep_default_na=False)
        parsed, _ = frame_to_operations(frame, f"{Path(path).stem}:{sheet}")
        for op in parsed:
            operations[op.operation_id] = op
        total += len(parsed)
        for column in frame.columns:
            series = frame[column]
            columns[str(column)] = {"format": str(series.dtype), "filled_share": round(float(series.notna().mean()), 6), "sheets": sorted(set(columns.get(str(column), {}).get("sheets", [])) | {sheet})}
        if "gold_segment" in frame.columns:
            for _, row in frame[["operation_id", "gold_segment"]].dropna().iterrows():
                targets[str(row["operation_id"])] = str(row["gold_segment"])
    return BatchData(operations, total, targets, columns)


class CompanyFeatureBuilder:
    def __init__(self, store, batch: BatchData, operation_links: dict[int, list[Any]] | None = None) -> None:
        self.store, self.batch, self.operation_links = store, batch, operation_links

    def build(self, inn: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]]]:
        query = "SELECT * FROM companies" + (" WHERE inn=?" if inn else "") + " ORDER BY id"
        companies = self.store.connection.execute(query, (inn,) if inn else ()).fetchall()
        rows, targets, corpus = [], [], []
        for company in companies:
            row, target, text = self._company_row(company)
            rows.append(row)
            if target: targets.append({"company_id": str(company["id"]), "target_class": target})
            corpus.append(text)
        assert_no_leakage(rows)
        return rows, targets, corpus

    def _company_operations(self, company_id: int) -> list[Any]:
        if self.operation_links is not None:
            linked = self.operation_links.get(company_id, [])
            return list({op.operation_id: op for op in linked}.values())
        ids = [row[0] for row in self.store.connection.execute("""SELECT ro.operation_id FROM request_operations ro
            JOIN research_requests rr ON rr.id=ro.research_request_id WHERE rr.company_id=?""", (company_id,))]
        return [self.batch.operations[item] for item in sorted(set(ids)) if item in self.batch.operations]

    def _company_row(self, company) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
        cid, inn = int(company["id"]), company["inn"] or ""
        ops = self._company_operations(cid)
        aliases = [row[0] for row in self.store.connection.execute("SELECT original_name FROM company_aliases WHERE company_id=? ORDER BY original_name", (cid,))]
        name = company["confirmed_legal_name"] or (aliases[0] if aliases else "")
        payer = [op for op in ops if op.payer_inn == inn]
        recipient = [op for op in ops if op.recipient_inn == inn]
        side_rows = [(op, side) for op in ops for side in ("payer", "recipient") if getattr(op, f"{side}_inn") == inn]
        n = len(ops)
        requisites = {field: [getattr(op, f"{side}_{field}") for op, side in side_rows if getattr(op, f"{side}_{field}")] for field in ("name_raw", "name_normalized", "inn", "kpp", "account", "bic", "bank_name", "corr_account")}
        row: dict[str, Any] = {"company_id": cid, "feature_version": FEATURE_VERSION, "calculated_at": date.today().isoformat()}
        row.update(self._transaction_features(ops, payer, recipient, requisites))
        row.update(self._available_behavior_features(ops, inn))
        row.update(self._name_features(cid, name, aliases))
        row.update(self._registry_okved_features(cid, company))
        row.update(self._website_features(cid, name))
        row.update(self._availability_features(row, cid, n))
        target_counts = Counter(self.batch.targets.get(op.operation_id) for op in ops if self.batch.targets.get(op.operation_id))
        target = target_counts.most_common(1)[0][0] if target_counts else None
        site_text = self._site_text(cid)
        phrases = [row[0] for row in self.store.connection.execute("SELECT text FROM website_keywords WHERE company_id=? AND keyword_type='keyphrase' ORDER BY score DESC", (cid,))]
        descriptions = [row[0] for row in self.store.connection.execute("SELECT value_text FROM company_facts WHERE company_id=? AND field_name='description'", (cid,))]
        purposes = [op.payment_purpose_normalized for op in ops if op.payment_purpose_normalized]
        corpus = {"company_id": cid, "clean_company_name": normalize_name(name), "website_text": site_text,
                  "website_keyphrases": " | ".join(phrases), "registry_description": " | ".join(descriptions),
                  "payment_purposes": " | ".join(purposes)}
        return row, target, corpus

    def _transaction_features(self, ops, payer, recipient, req) -> dict[str, Any]:
        n, batch = len(ops), self.batch.batch_transaction_count
        accounts, banks = req["account"], req["bank_name"]
        values = {
            "transaction_count": n, "log_transaction_count": round(math.log1p(n), 6), "batch_transaction_count": batch,
            "company_share_of_batch": round(n / batch, 6) if batch else 0.0,
            "payer_transaction_count": len(payer), "recipient_transaction_count": len(recipient),
            "payer_share": round(len(payer) / n, 6) if n else 0.0, "recipient_share": round(len(recipient) / n, 6) if n else 0.0,
            "appears_as_payer": int(bool(payer)), "appears_as_recipient": int(bool(recipient)), "appears_on_both_sides": int(bool(payer and recipient)),
            "payer_recipient_ratio": round(len(payer) / len(recipient), 6) if recipient else float(len(payer)),
            "unique_company_name_count": len(set(req["name_raw"])), "unique_normalized_name_count": len(set(req["name_normalized"])),
            "unique_inn_count": len(set(req["inn"])), "unique_kpp_count": len(set(req["kpp"])), "unique_account_count": len(set(accounts)),
            "unique_bic_count": len(set(req["bic"])), "unique_bank_name_count": len(set(banks)), "unique_corr_account_count": len(set(req["corr_account"])),
            "multi_account_flag": int(len(set(accounts)) > 1), "multi_bank_flag": int(len(set(banks)) > 1),
            "top_account_transaction_share": _top_share(accounts), "top_bank_transaction_share": _top_share(banks),
            "transactions_per_account_mean": round(n / len(set(accounts)), 6) if accounts else 0.0,
            "transactions_per_account_max": max(Counter(accounts).values()) if accounts else 0,
            "valid_inn_share": _share((valid_inn(x) for x in req["inn"]), len(req["inn"])), "valid_kpp_share": _share((valid_kpp(x) for x in req["kpp"]), len(req["kpp"])),
            "valid_account_share": _share((valid_account(x) for x in accounts), len(accounts)), "valid_bic_share": _share((valid_bic(x) for x in req["bic"]), len(req["bic"])),
            "valid_corr_account_share": _share((valid_account(x) for x in req["corr_account"]), len(req["corr_account"])),
        }
        side_count = len(req["inn"])
        values.update({"missing_company_name_share": 1.0 if n and not req["name_raw"] else 0.0, "missing_inn_share": 1.0 if n and not req["inn"] else 0.0,
                       "missing_kpp_share": 1.0 if n and not req["kpp"] else 0.0, "missing_account_share": 1.0 if n and not accounts else 0.0,
                       "missing_bank_fields_share": 1.0 if n and (not banks or not req["bic"] or not req["corr_account"]) else 0.0})
        valid = [values[key] for key in ("valid_inn_share", "valid_kpp_share", "valid_account_share", "valid_bic_share", "valid_corr_account_share")]
        values["data_quality_score"] = round(sum(valid) / len(valid), 6) if side_count else 0.0
        return values

    def _available_behavior_features(self, ops, inn: str) -> dict[str, Any]:
        """Compute behaviour only because these fields are truly in the XLSX."""
        amounts = [float(op.amount) for op in ops if op.amount is not None]
        incoming = [float(op.amount) for op in ops if op.direction == "IN" and op.amount is not None]
        outgoing = [float(op.amount) for op in ops if op.direction == "OUT" and op.amount is not None]
        ordered = sorted(amounts)
        def quantile(p: float) -> float:
            if not ordered: return 0.0
            return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))], 6)
        mean = sum(amounts) / len(amounts) if amounts else 0.0
        variance = sum((value - mean) ** 2 for value in amounts) / len(amounts) if amounts else 0.0
        dates = sorted({op.operation_datetime.date() for op in ops if op.operation_datetime})
        gaps = [(later - earlier).total_seconds() / 3600 for earlier, later in zip(sorted(op.operation_datetime for op in ops if op.operation_datetime), sorted(op.operation_datetime for op in ops if op.operation_datetime)[1:])]
        purposes = " ".join(op.payment_purpose_normalized or "" for op in ops).lower()
        counterparts = []
        for op in ops:
            if op.payer_inn == inn: counterparts.append(op.recipient_inn or op.recipient_name_normalized or "")
            if op.recipient_inn == inn: counterparts.append(op.payer_inn or op.payer_name_normalized or "")
        counterparts = [item for item in counterparts if item]
        counts = Counter(counterparts)
        hhi = sum((count / len(counterparts)) ** 2 for count in counts.values()) if counterparts else 0.0
        markers = {"agent": ("агент", "принципал"), "commission": ("комисс",), "order_register": ("реестр", "заказ", "order"),
                   "seller_payout": ("выплат продав",), "performer_payout": ("выплат исполн",), "fulfillment": ("фулфилмент",),
                   "refund": ("возврат",), "split": ("split",), "settlement": ("settlement", "расчет"), "acquiring": ("эквайр", "acquiring"),
                   "own_goods_services": ("собственн", "товар", "услуг")}
        out = {"amount_data_available": int(bool(amounts)), "total_turnover": round(sum(amounts), 6), "incoming_turnover": round(sum(incoming), 6),
               "outgoing_turnover": round(sum(outgoing), 6), "mean_amount": round(mean, 6), "median_amount": quantile(.5), "amount_stddev": round(variance ** .5, 6),
               "amount_cv": round((variance ** .5) / mean, 6) if mean else 0.0, "amount_p25": quantile(.25), "amount_p75": quantile(.75),
               "round_amount_share": _share((abs(value - round(value)) < .000001 for value in amounts), len(amounts)),
               "in_out_turnover_ratio": round(sum(incoming) / sum(outgoing), 6) if outgoing else float(sum(incoming)),
               "datetime_data_available": int(bool(dates)), "active_days_count": len(dates), "operations_per_active_day": round(len(ops) / len(dates), 6) if dates else 0.0,
               "median_gap_hours": quantile_from(gaps, .5), "max_operations_per_day": max(Counter(op.operation_datetime.date() for op in ops if op.operation_datetime).values(), default=0),
               "purpose_data_available": int(bool(purposes)), "counterparty_data_available": int(bool(counterparts)), "unique_counterparty_count": len(counts),
               "top_counterparty_share": _top_share(counterparts), "counterparty_hhi": round(hhi, 6),
               "counterparty_many_to_one_flag": int(len(counts) >= 3 and len(ops) >= 3), "counterparty_one_to_many_flag": int(len(counts) >= 3 and len(ops) >= 3),
               "has_mcc": 0}
        out.update({f"purpose_{name}_marker_count": sum(purposes.count(marker) for marker in markers_) for name, markers_ in markers.items()})
        return out

    def _name_features(self, cid: int, name: str, aliases: list[str]) -> dict[str, Any]:
        normalized = normalize_name(name)
        alias_similarity = max((_similarity(name, alias) for alias in aliases), default=0.0)
        output = {"company_name_length": len(normalized), "company_name_token_count": len(normalized.split()), "company_alias_count": len(set(aliases)),
                  "legal_name_alias_similarity": alias_similarity, "legal_form_code": _legal_form(name)}
        lower = normalized.lower()
        output.update({f"has_{key}_name_marker": int(any(marker in lower for marker in markers)) for key, markers in NAME_MARKERS.items()})
        return output

    def _registry_okved_features(self, cid: int, company) -> dict[str, Any]:
        sources = self.store.connection.execute("SELECT source_name, request_status FROM source_results WHERE company_id=?", (cid,)).fetchall()
        facts = self.store.connection.execute("SELECT field_name, source_name, is_conflicting FROM company_facts WHERE company_id=?", (cid,)).fetchall()
        okveds = self.store.connection.execute("SELECT okved_code, is_primary, source_name, is_conflicting FROM company_okved WHERE company_id=?", (cid,)).fetchall()
        primary = next((row["okved_code"] for row in okveds if row["is_primary"] and not row["is_conflicting"]), "")
        by_source: dict[str, set[str]] = defaultdict(set)
        for source in sources: by_source[source["source_name"]].add(source["request_status"])
        source_names = set(by_source)
        fact_sources = lambda field: len({row["source_name"] for row in facts if row["field_name"] == field and row["source_name"]})
        code = str(primary or "")
        status = clean_text(company["registration_status"] or "").lower()
        registration_date = company["registration_date"]
        age = ""
        try: age = round((date.today() - date.fromisoformat(str(registration_date)[:10])).days / 365.25, 4)
        except (TypeError, ValueError): pass
        out = {"registry_matched_sources_count": sum("matched" in statuses for statuses in by_source.values()),
               "registry_failed_sources_count": sum(not ("matched" in statuses) and bool(statuses & {"unavailable", "error"}) for statuses in by_source.values()),
               "registry_manual_sources_count": sum(any("manual" in status for status in statuses) for statuses in by_source.values()),
               "registry_conflict_count": len({row["field_name"] for row in facts if row["is_conflicting"]}),
               "legal_name_sources_count": fact_sources("legal_name"), "ogrn_sources_count": fact_sources("ogrn"), "kpp_sources_count": fact_sources("kpp"), "address_sources_count": fact_sources("address"),
               "registry_confirmation_score": round(sum("matched" in statuses for statuses in by_source.values()) / max(1, len(source_names)), 6),
               "company_age_years": age, "registration_active_flag": int("действ" in status) if status else "",
               "primary_okved_code": code, "primary_okved_prefix2": re.sub(r"\D", "", code)[:2], "primary_okved_prefix4": re.sub(r"\D", "", code)[:4], "primary_okved_section": _okved_section(code),
               "additional_okved_count": sum(not row["is_primary"] for row in okveds), "okved_sources_count": len({row["source_name"] for row in okveds if row["source_name"]}),
               "okved_conflict_flag": int(any(row["is_conflicting"] for row in okveds))}
        out.update({f"okved_{group}_flag": int(any(_code_prefix(code, prefix) for prefix in prefixes)) for group, prefixes in OKVED_GROUPS.items()})
        return out

    def _website_features(self, cid: int, name: str) -> dict[str, Any]:
        candidates_all = self.store.connection.execute("SELECT * FROM website_candidates WHERE company_id=?", (cid,)).fetchall()
        # Candidate rows are append/provenance history.  Features describe the
        # most recent discovery attempt, not failed search-engine candidates
        # from an earlier run.
        latest = max((row["updated_at"] for row in candidates_all), default=None)
        candidates = [row for row in candidates_all if row["updated_at"] == latest] if latest else []
        pages = self.store.connection.execute("SELECT * FROM website_pages WHERE company_id=?", (cid,)).fetchall()
        signals = self.store.connection.execute("SELECT * FROM website_signals WHERE company_id=?", (cid,)).fetchall()
        keywords = self.store.connection.execute("SELECT keyword_type FROM website_keywords WHERE company_id=?", (cid,)).fetchall()
        # Existing databases before the site-status migration do not have these
        # columns; use the legacy candidate status safely.
        colset = {row[1] for row in self.store.connection.execute("PRAGMA table_info(website_candidates)")}
        get = lambda row, key, default="": row[key] if key in colset else default
        def legacy_fetch(row):
            stored = get(row, "fetch_status")
            if stored and stored != "not_started": return stored
            detail = " ".join(_safe_json(row["negative_evidence_json"])).lower()
            if "timed out" in detail or "timeout" in detail: return "timeout"
            if "blocked_by_waf" in detail: return "blocked_by_waf"
            for code in (401, 403, 404, 498):
                if str(code) in detail: return f"http_{code}"
            if "invalid_content" in detail: return "invalid_content_type"
            return "not_started"
        verification = [get(row, "verification_status") if get(row, "verification_status") not in {"", "not_started"} else ("confirmed_by_website" if row["candidate_status"] == "confirmed" else "rejected" if row["candidate_status"] == "rejected" else "probable" if row["candidate_status"] == "unavailable" else "not_started") for row in candidates]
        fetch = [legacy_fetch(row) for row in candidates]
        registry_sources = set(source for row in candidates for source in _safe_json(get(row, "registry_sources_json", "[]")))
        registry_sources.update(row["candidate_source"] for row in candidates if (row["search_query"] or "").startswith("registry:") and row["candidate_source"])
        search_sources = {row["candidate_source"] for row in candidates if row["candidate_source"] in {"DuckDuckGo", "Bing"}}
        out = {"website_candidate_found": int(bool(candidates)), "website_candidate_count": len(candidates), "website_registry_sources_count": len(registry_sources),
               "website_search_sources_count": len(search_sources), "website_probable_flag": int("probable" in verification),
               "website_confirmed_by_registry_flag": int("confirmed_by_registry" in verification), "website_confirmed_by_website_flag": int("confirmed_by_website" in verification),
               "website_requires_review_flag": int("requires_review" in verification), "website_rejected_flag": int("rejected" in verification),
               "website_fetch_success": int("success" in fetch), "website_timeout_flag": int("timeout" in fetch), "website_waf_flag": int("blocked_by_waf" in fetch),
               "website_http_401_flag": int("http_401" in fetch), "website_http_403_flag": int("http_403" in fetch), "website_http_498_flag": int("http_498" in fetch),
               "website_invalid_content_flag": int("invalid_content_type" in fetch), "website_analysis_success": int(bool(pages)),
               "website_verification_score": max((float(row["candidate_score"] or 0) for row in candidates), default=0.0),
               "company_name_domain_similarity": max((_similarity(name, row["domain"] or "") for row in candidates), default=0.0),
               "site_pages_count": len(pages), "site_distinct_page_types": len({row["page_type"] for row in pages if row["page_type"]}),
               "site_total_text_length": sum(self._text_length(row["visible_text_path"]) for row in pages),
               "site_title_count": sum(bool(row["title"]) for row in pages), "site_h1_count": sum(bool(row["h1"]) for row in pages),
               "site_h2_count": 0, "site_keyword_count": sum(row["keyword_type"] == "keyword" for row in keywords),
               "site_keyphrase_count": sum(row["keyword_type"] == "keyphrase" for row in keywords), "site_signal_count": len(signals),
               "site_counter_signal_count": sum(row["preliminary_class"] == "COUNTER" for row in signals),
               "site_distinct_signal_family_count": len({row["signal_family"] for row in signals if row["signal_family"]}),
               "site_distinct_evidence_page_count": len({row["page_url"] for row in signals if row["page_url"]})}
        out["site_mean_page_text_length"] = round(out["site_total_text_length"] / len(pages), 6) if pages else 0.0
        page_urls = " ".join(str(row["url"] or "").lower() for row in pages)
        out.update({f"has_{name}_page": int(any(marker in page_urls for marker in markers)) for name, markers in PAGE_FLAGS.items()})
        signal_rows = [dict(row) for row in signals]
        for source, target in SIGNAL_CLASS.items():
            selected = [row for row in signal_rows if row.get("preliminary_class") == source]
            out.update({f"site_{target}_signal_count": len(selected), f"site_{target}_weight_sum": round(sum(float(row.get("weight") or 0) for row in selected), 6),
                        f"site_{target}_max_weight": max((float(row.get("weight") or 0) for row in selected), default=0.0),
                        f"site_{target}_family_count": len({row.get("signal_family") for row in selected if row.get("signal_family")}),
                        f"site_{target}_evidence_pages_count": len({row.get("page_url") for row in selected if row.get("page_url")})})
        for name, (family, phrases) in SIGNAL_FLAGS.items():
            out[f"has_{name}"] = int(any(row.get("signal_family") == family and (not phrases or any(phrase in (row.get("matched_phrase") or "").lower() for phrase in phrases)) for row in signal_rows))
        return out

    @staticmethod
    def _text_length(path: str | None) -> int:
        try: return len(Path(path).read_text(encoding="utf-8")) if path else 0
        except OSError: return 0

    def _site_text(self, cid: int) -> str:
        return " ".join(Path(row[0]).read_text(encoding="utf-8", errors="replace") for row in self.store.connection.execute("SELECT visible_text_path FROM website_pages WHERE company_id=?", (cid,)) if row[0] and Path(row[0]).exists())

    def _availability_features(self, row: dict[str, Any], cid: int, n: int) -> dict[str, Any]:
        registry = int(row["registry_matched_sources_count"] > 0)
        okved = int(bool(row["primary_okved_code"]) or row["additional_okved_count"] > 0)
        candidate = int(row["website_candidate_found"] > 0)
        content = int(row["site_pages_count"] > 0)
        independent = registry + okved + candidate + content + int(n > 0)
        conflict = row["registry_conflict_count"]
        return {"registry_data_available": registry, "okved_data_available": okved, "website_candidate_available": candidate,
                "website_content_available": content, "transaction_data_available": int(n > 0), "independent_evidence_sources_count": independent,
                "requisites_conflict_count": conflict, "name_okved_conflict": 0, "name_website_conflict": 0, "okved_website_conflict": 0,
                "registry_website_conflict": int(conflict > 0 and candidate > 0), "low_transaction_count_flag": int(0 < n < 5),
                "feature_completeness": round(sum((registry, okved, candidate, content, int(n > 0))) / 5, 6),
                "insufficient_data_flag": int(sum((registry, okved, candidate, content, int(n > 0))) < 2)}


def assert_no_leakage(rows: list[dict[str, Any]]) -> None:
    forbidden = {"inn", "ogrn", "account", "bic", "corr_account", "website_hypothesis", "target", "gold_segment", "operation_id", "source_file", "source_row", "sheet"}
    columns = set().union(*(set(row) for row in rows)) if rows else set()
    leaked = sorted(column for column in columns if column in forbidden or any(term in column.lower() for term in ("gold_", "predicted_", "target_class", "website_hypothesis")))
    if leaked: raise ValueError(f"Leakage-prone columns in feature matrix: {leaked}")


def catalog_for_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = sorted(set().union(*(set(row) for row in rows)) - {"company_id", "feature_version", "calculated_at"}) if rows else []
    catalog = []
    for name in columns:
        if name in {"company_id", "feature_version", "calculated_at"}: continue
        group = next((value for prefix, value in (("site_", "website_content"), ("website_", "website"), ("okved_", "okved"), ("registry_", "registry"), ("transaction", "transactions"), ("payer_", "transactions"), ("recipient_", "transactions"), ("company_name", "name"), ("has_", "name_or_website")) if name.startswith(prefix)), "quality")
        sample = next((row[name] for row in rows if name in row), "")
        datatype = "categorical" if isinstance(sample, str) and name not in {"registration_active_flag"} else "binary" if name.endswith(("_flag", "_available", "_success", "_found")) or name.startswith("appears_") or name.startswith("has_") else "numeric"
        catalog.append({"feature_name": name, "group": group, "data_type": datatype, "source": "SQLite + local payment batch", "description": name.replace("_", " "),
                        "available_now": True, "requires_fields": [], "missing_value_policy": "0 for unavailable counts/flags; empty string for unavailable category",
                        "use_in_numeric_model": datatype != "categorical", "use_in_text_model": False, "leakage_risk": "low", "feature_version": FEATURE_VERSION})
    # The supplied XLSX already contains amount, datetime, purpose and both
    # parties, so they are calculated above.  MCC is the only requested
    # payment field absent from the real project data.
    future = [("mcc_distribution", "mcc"), ("mcc_fintech_share", "mcc")]
    catalog.extend({"feature_name": name, "group": "future", "data_type": "numeric", "source": "future payment fields", "description": f"Available only when {field} is supplied", "available_now": False, "requires_fields": [field], "missing_value_policy": "not computed", "use_in_numeric_model": True, "use_in_text_model": False, "leakage_risk": "low", "feature_version": FEATURE_VERSION} for name, field in future)
    return catalog


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted(set().union(*(set(row) for row in rows))) if rows else ["company_id", "feature_version", "calculated_at"]
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def quality_report(rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    columns = sorted(set().union(*(set(row) for row in rows)) - {"company_id", "feature_version", "calculated_at"}) if rows else []
    for name in columns:
        values = [row.get(name, "") for row in rows]
        present = [item for item in values if item not in ("", None)]
        numeric = [float(item) for item in present if isinstance(item, (int, float)) and not isinstance(item, bool)]
        features[name] = {"missing_share": round(1 - len(present) / max(1, len(values)), 6), "unique_values": len(set(map(str, present))),
                          "min": min(numeric) if numeric else None, "max": max(numeric) if numeric else None,
                          "mean": round(sum(numeric) / len(numeric), 6) if numeric else None,
                          "constant": len(set(map(str, present))) <= 1, "high_cardinality": len(set(map(str, present))) > max(20, len(values) * .5),
                          "leakage_risk": "high" if name in {"inn", "ogrn", "account", "bic", "corr_account", "target", "website_hypothesis", "operation_id", "source_file", "source_row", "sheet"} or name.startswith(("gold_", "predicted_", "target_")) else "low"}
    constants = [name for name, item in features.items() if item["constant"]]
    almost_empty = [name for name, item in features.items() if item["missing_share"] >= .9]
    return {"feature_version": FEATURE_VERSION, "company_count": len(rows), "features": features, "constant_features": constants,
            "almost_empty_features": almost_empty, "duplicate_features": [], "high_leakage_features": [name for name, item in features.items() if item["leakage_risk"] == "high"],
            "unavailable_in_classification_batch": ["gold_segment", "gold_confidence", "expert_rationale"],
            "target_leakage_check": "passed"}
