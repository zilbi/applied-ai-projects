"""Local, INN-only linkage of XLSX gold labels to company-level rows."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .company_features import BatchData, CompanyFeatureBuilder, assert_no_leakage, write_csv
from .ingestion import frame_to_operations
from .normalization import clean_text
from .validation import valid_inn

TRAIN_SHEET = "Обучение_с_ответами"
PREDICT_SHEET = "Классификация_без_ответов"

# These strings are actual values in the current training sheet.  They state
# the labelled entity's direction; they are not an inferred ML rule.
ROLE_SIDES = {
    "возврат клиенту": "payer", "возврат комиссии": "payer", "возможная комиссия": "recipient",
    "неоднозначная выплата": "payer", "неоднозначное поступление": "recipient",
    "обычный хозяйственный расход": "payer", "платформа возвращает оплату": "payer",
    "платформа выплачивает участнику": "payer", "платформа получает вознаграждение": "recipient",
    "платформа получает оплату заказа": "recipient", "посредник выполняет возврат": "payer",
    "посредник перечисляет остаток": "payer", "посредник получает комиссию": "recipient",
    "посредник получает платёж": "recipient", "поставщик платёжной услуги": "recipient",
    "поставщик эквайринга получает комиссию": "recipient", "продавец собственного товара/услуги": "recipient",
    "расход на эквайринг": "payer",
}
TARGETS = {
    "а платежный посредник": "A", "a платежный посредник": "A",
    "b платформа marketplace": "B", "в платформа marketplace": "B",
    "не финтех": "NON_FINTECH",
}


def _norm_label(value: Any) -> str:
    value = clean_text(value).lower().replace("—", " ").replace("–", " ").replace("-", " ")
    return " ".join(value.replace("/", " ").split())


def normalize_target(value: Any) -> tuple[str | None, str]:
    raw = "" if value is None else str(value).strip()
    if not raw: return None, "missing"
    return TARGETS.get(_norm_label(raw)), "confirmed" if _norm_label(raw) in TARGETS else "unknown_label"


def _inn(value: Any) -> str:
    value = "" if value is None else str(value).strip()
    return value if valid_inn(value) else ""


@dataclass
class LinkageResult:
    mapping: list[dict[str, Any]]
    target_rows: list[dict[str, Any]]
    unmatched: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    train_links: dict[int, list[Any]]
    predict_links: dict[int, list[Any]]
    train_batch: BatchData
    predict_batch: BatchData
    report: dict[str, Any]


def _frames(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Do not let pandas convert text INNs to numbers; XLSX itself is untouched.
    return tuple(pd.read_excel(path, sheet_name=sheet, dtype=str, keep_default_na=False) for sheet in (TRAIN_SHEET, PREDICT_SHEET))  # type: ignore[return-value]


def _expected_inns(train: pd.DataFrame) -> dict[str, str]:
    by_gold: dict[str, Counter[str]] = defaultdict(Counter)
    for _, row in train.iterrows():
        side = ROLE_SIDES.get(str(row.get("company_role_in_operation", "")))
        if side:
            inn = _inn(row.get(f"{side}_inn"))
            if inn: by_gold[str(row.get("gold_company_id", ""))][inn] += 1
    return {gold: next(iter(values)) for gold, values in by_gold.items() if len(values) == 1}


def _operations(frame: pd.DataFrame, source: str) -> dict[str, Any]:
    parsed, warnings = frame_to_operations(frame, source)
    if warnings: raise ValueError(f"Не удалось разобрать {source}: {warnings[:3]}")
    return {op.operation_id: op for op in parsed}


def link_targets(store, path: str | Path, *, persist: bool = False) -> LinkageResult:
    train, predict = _frames(path)
    required = {"gold_company_id", "gold_canonical_company_name", "company_role_in_operation", "gold_segment", "operation_id"}
    missing = required - set(train.columns)
    if missing: raise ValueError(f"В обучающем листе нет обязательных колонок: {sorted(missing)}")
    expected = _expected_inns(train)
    semantic_roles = set(train["company_role_in_operation"].astype(str))
    unknown_roles = sorted(semantic_roles - set(ROLE_SIDES) - {"неполная операция"})
    if unknown_roles: raise ValueError(f"Неоднозначные роли target: {unknown_roles}")
    train_ops, predict_ops = _operations(train, TRAIN_SHEET), _operations(predict, PREDICT_SHEET)
    mapping: list[dict[str, Any]] = []; unmatched: list[dict[str, Any]] = []
    created, exact = 0, 0
    company_by_inn = {row["inn"]: int(row["id"]) for row in store.connection.execute("SELECT id, inn FROM companies WHERE inn IS NOT NULL")}
    train_links: dict[int, list[Any]] = defaultdict(list)
    for index, row in train.iterrows():
        source_row, role, gold = index + 2, str(row.get("company_role_in_operation", "")), str(row.get("gold_company_id", ""))
        side = ROLE_SIDES.get(role)
        if side is None:
            expected_inn = expected.get(gold, "")
            matches = [candidate for candidate in ("payer", "recipient") if _inn(row.get(f"{candidate}_inn")) == expected_inn]
            side = matches[0] if len(matches) == 1 else None
        raw_target = row.get("gold_segment", "")
        target, target_status = normalize_target(raw_target)
        inn = _inn(row.get(f"{side}_inn")) if side else ""
        item = {"source_sheet": TRAIN_SHEET, "source_row": source_row, "operation_id": str(row.get("operation_id", "")), "target_side": side or "",
                "source_inn": inn, "source_name": str(row.get(f"{side}_name_normalized", "")) if side else "", "company_id": "",
                "mapping_method": "exact_valid_inn", "mapping_status": "", "raw_target": raw_target, "normalized_target": target or "", "target_status": target_status,
                "gold_company_id": gold, "gold_company_name": str(row.get("gold_canonical_company_name", ""))}
        if not side:
            item["mapping_status"] = "requires_review"; item["mapping_method"] = "unresolved_target_side"
        elif not inn:
            item["mapping_status"] = "requires_review"; item["mapping_method"] = "missing_or_invalid_target_inn"
        elif target_status != "confirmed":
            item["mapping_status"] = "unknown_label"
        else:
            cid = company_by_inn.get(inn)
            if cid is None:
                if not persist:
                    item["mapping_status"] = "would_create"; item["mapping_method"] = "exact_valid_inn_new_company"
                    mapping.append(item); unmatched.append(dict(item)); continue
                request = {"lookup_id": f"target-link:{TRAIN_SHEET}:{inn}", "inn": inn,
                           "legal_name_candidates": [item["source_name"]], "account_candidates": [str(row.get(f"{side}_account", ""))],
                           "operation_ids": [], "source_sides": [side], "lookup_status": "target_linked_local"}
                cid = store.import_request(request, "fintech_payments_dataset_2000.xlsx", source_row)
                cid = int(store.connection.execute("SELECT company_id FROM research_requests WHERE id=?", (cid,)).fetchone()[0])
                company_by_inn[inn] = cid; created += 1
            exact += 1; item["company_id"] = cid; item["mapping_status"] = "matched"; train_links[cid].append(train_ops[item["operation_id"]])
        mapping.append(item)
        if item["mapping_status"] != "matched": unmatched.append(dict(item))
    # Target aggregation is deliberately never majority-voted.
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in mapping:
        if item["mapping_status"] == "matched": grouped[int(item["company_id"])].append(item)
    target_rows: list[dict[str, Any]] = []; conflicts: list[dict[str, Any]] = []
    for cid, rows in sorted(grouped.items()):
        labels = Counter(row["normalized_target"] for row in rows)
        status = "confirmed" if len(labels) == 1 else "conflicting"
        target = next(iter(labels)) if status == "confirmed" else ""
        out = {"company_id": cid, "target_class": target, "target_status": status, "labeled_operations_count": len(rows), "source_sheet": TRAIN_SHEET}
        target_rows.append(out)
        if status == "conflicting": conflicts.append({**out, "classes": json.dumps(dict(labels), ensure_ascii=False), "operation_ids": json.dumps([row["operation_id"] for row in rows]), "source_rows": json.dumps([row["source_row"] for row in rows])})
    # Prediction has no target-bearing side. Existing parser semantics therefore
    # retain each valid legal entity found on either side, with no labels.
    predict_links: dict[int, list[Any]] = defaultdict(list)
    for _, row in predict.iterrows():
        op = predict_ops[str(row.get("operation_id", ""))]
        for side in ("payer", "recipient"):
            inn = _inn(row.get(f"{side}_inn"))
            if not inn: continue
            cid = company_by_inn.get(inn)
            if cid is None:
                if not persist:
                    continue
                request = {"lookup_id": f"target-link:{PREDICT_SHEET}:{inn}", "inn": inn, "legal_name_candidates": [str(row.get(f"{side}_name_normalized", ""))],
                           "account_candidates": [str(row.get(f"{side}_account", ""))], "operation_ids": [], "source_sides": [side], "lookup_status": "predict_linked_local"}
                rid = store.import_request(request, "fintech_payments_dataset_2000.xlsx", int(row.name) + 2)
                cid = int(store.connection.execute("SELECT company_id FROM research_requests WHERE id=?", (rid,)).fetchone()[0]); company_by_inn[inn] = cid; created += 1
            predict_links[cid].append(op)
    train_batch = BatchData(train_ops, len(train), {}, {})
    predict_batch = BatchData(predict_ops, len(predict), {}, {})
    overlap = sorted(set(train_links) & set(predict_links))
    report = {"train_rows": len(train), "predict_rows": len(predict), "unique_labeled_companies": len(grouped), "exact_inn_matches": exact,
              "created_companies": created, "unmatched_rows": len(unmatched), "conflicting_targets": len(conflicts), "unknown_labels": sum(row["target_status"] == "unknown_label" for row in mapping),
              "missing_or_invalid_inn": sum(row["mapping_method"] == "missing_or_invalid_target_inn" for row in mapping), "target_side_unresolved": sum(row["mapping_method"] == "unresolved_target_side" for row in mapping),
              "target_distribution_companies": dict(Counter(row["target_class"] for row in target_rows if row["target_status"] == "confirmed")), "train_predict_overlap": len(overlap),
              "operation_id_overlap": len(set(train_ops) & set(predict_ops)), "semantic_role_count": len(ROLE_SIDES), "expected_inn_groups": len(expected)}
    return LinkageResult(mapping, target_rows, unmatched, conflicts, train_links, predict_links, train_batch, predict_batch, report)


def build_ml_files(store, result: LinkageResult, root: str | Path) -> dict[str, Any]:
    root = Path(root); out = root / "results" / "ml"; out.mkdir(parents=True, exist_ok=True)
    train_rows, _, _ = CompanyFeatureBuilder(store, result.train_batch, result.train_links).build()
    predict_rows, _, _ = CompanyFeatureBuilder(store, result.predict_batch, result.predict_links).build()
    confirmed = {row["company_id"] for row in result.target_rows if row["target_status"] == "confirmed"}
    train_rows = [row for row in train_rows if row["company_id"] in confirmed]
    feature_cols = sorted(set().union(*(set(row) for row in train_rows + predict_rows)) - {"calculated_at"})
    def align(rows): return [{key: row.get(key, "") for key in feature_cols} for row in rows]
    train_rows, predict_rows = align(train_rows), align(predict_rows)
    assert_no_leakage(train_rows); assert_no_leakage(predict_rows)
    write_csv(out / "train_company_features.csv", train_rows); write_csv(out / "predict_company_features.csv", predict_rows)
    write_csv(out / "train_company_targets.csv", [row for row in result.target_rows if row["target_status"] == "confirmed"])
    write_csv(out / "company_target_mapping.csv", result.mapping); write_csv(out / "target_conflicts.csv", result.conflicts); write_csv(out / "unmatched_labeled_rows.csv", result.unmatched)
    overlap = []
    for cid in sorted(set(result.train_links) & set(result.predict_links)):
        c = store.connection.execute("SELECT inn, confirmed_legal_name FROM companies WHERE id=?", (cid,)).fetchone()
        overlap.append({"company_id": cid, "inn": c["inn"], "legal_name": c["confirmed_legal_name"], "train_operations_count": len(result.train_links[cid]), "predict_operations_count": len(result.predict_links[cid])})
    write_csv(out / "train_predict_company_overlap.csv", overlap)
    # SQLite keeps the same row-level provenance as the CSV report.  The
    # primary key makes a repeated local run idempotent.
    store.connection.execute("DELETE FROM company_target_mappings WHERE source_sheet=?", (TRAIN_SHEET,))
    for row in result.mapping:
        store.connection.execute(
            """INSERT INTO company_target_mappings(source_sheet, source_row, operation_id, target_side, source_inn,
               source_name, company_id, mapping_method, mapping_status, raw_target, normalized_target, target_status, gold_company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["source_sheet"], row["source_row"], row["operation_id"], row["target_side"], row["source_inn"], row["source_name"],
             row["company_id"] or None, row["mapping_method"], row["mapping_status"], str(row["raw_target"]), row["normalized_target"], row["target_status"], row["gold_company_id"]),
        )
    store.connection.execute("DELETE FROM company_targets")
    from .research_store import utcnow
    for row in result.target_rows:
        store.connection.execute("INSERT INTO company_targets(company_id, target_class, target_status, labeled_operations_count, source_sheet, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (row["company_id"], row["target_class"] or None, row["target_status"], row["labeled_operations_count"], row["source_sheet"], utcnow()))
    result.report.update({"train_feature_rows": len(train_rows), "predict_feature_rows": len(predict_rows), "feature_count": len(feature_cols), "feature_columns_match": True})
    (out / "linkage_quality_report.json").write_text(json.dumps(result.report, ensure_ascii=False, indent=2), encoding="utf-8")
    return result.report
