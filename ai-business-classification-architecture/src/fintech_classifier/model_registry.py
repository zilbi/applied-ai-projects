"""Strict loader for the current local structured production candidate."""
from __future__ import annotations

import hashlib
import json
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib


class ModelRegistryError(RuntimeError):
    """Raised before any prediction when the frozen model contract is broken."""


@dataclass(frozen=True)
class ProductionModels:
    primary: Any
    supporting_logreg: Any | None
    supporting_hgb: Any | None
    name: str
    version: str
    feature_schema: str
    fingerprint: str
    columns: tuple[str, ...]
    provenance: dict[str, Any]


def feature_fingerprint(columns: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(columns).encode("utf-8")).hexdigest()


class ModelRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self.time_data = self.root / "results" / "synthetic_time_v1"
        self.data = self.root / "results" / "synthetic_1000_v2"
        self.comparison_dir = self.data / "model_comparison"

    def load_production(self) -> ProductionModels:
        # The time-augmented model is a new, separately versioned candidate.
        # Its complete contract must exist before it can replace frozen v2.
        time_schema_path = self.time_data / "feature_schema.json"
        time_candidate_path = self.time_data / "production_candidate.json"
        if time_schema_path.exists() and time_candidate_path.exists():
            schema = json.loads(time_schema_path.read_text(encoding="utf-8"))
            candidate = json.loads(time_candidate_path.read_text(encoding="utf-8"))
            columns = tuple(schema.get("ordered_columns", []))
            expected = schema.get("feature_schema_fingerprint")
            artifact = self.time_data / str(candidate.get("artifact", ""))
            if (candidate.get("model") == "catboost" and columns and expected
                    and feature_fingerprint(columns) == expected and artifact.exists()
                    and candidate.get("feature_fingerprint") == expected):
                return ProductionModels(
                    primary=joblib.load(artifact), supporting_logreg=None, supporting_hgb=None,
                    name="CatBoost", version=str(candidate.get("model_version", "synthetic-time-v1")),
                    feature_schema=str(schema.get("feature_schema_name")), fingerprint=expected, columns=columns,
                    provenance={"production_candidate": str(time_candidate_path.relative_to(self.root)),
                                "training_report": str((self.time_data / "training_report.json").relative_to(self.root)),
                                "warning": "time features are synthetic; reported holdout metrics are not real-world validation"},
                )
        schema_path = self.data / "feature_schema.json"
        report_path = self.comparison_dir / "full_metrics.json"
        if not schema_path.exists() or not report_path.exists():
            raise ModelRegistryError("Не найдены frozen synthetic-v2 feature schema или model comparison report.")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        columns = tuple(schema.get("ordered_columns", []))
        expected = schema.get("feature_schema_fingerprint")
        if not columns or feature_fingerprint(columns) != expected:
            raise ModelRegistryError("Feature fingerprint в frozen schema не совпадает с порядком колонок.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_rows = report.get("results", [])
        # A partial force-rerun can leave ``full_metrics.json`` with just the
        # rerun rows while the canonical comparison CSV still has all frozen
        # comparisons.  Prefer the JSON when complete, otherwise fall back.
        comparison_csv = self.comparison_dir / "model_comparison.csv"
        if not any(row.get("model") == "catboost" for row in report_rows) and comparison_csv.exists():
            with comparison_csv.open(encoding="utf-8") as handle:
                report_rows = list(csv.DictReader(handle))
        matches = [row for row in report_rows if row.get("model") == "catboost"
                   and row.get("training_regime") == "confirmed_plus_synthetic"
                   and row.get("feature_schema") == "common-v2-22-features"
                   and row.get("feature_fingerprint") == expected]
        manifest_path = self.comparison_dir / "production_candidate.json"
        # The full report can be incomplete after a previous partial rerun. A
        # frozen manifest, generated from that report, is the immutable
        # fallback; it still requires the exact schema + artifact contract.
        if not matches and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if all(manifest.get(key) == value for key, value in {
                "model": "catboost", "training_regime": "confirmed_plus_synthetic",
                "feature_schema": "common-v2-22-features", "feature_fingerprint": expected,
            }.items()):
                matches = [manifest]
        if not matches:
            raise ModelRegistryError("Production CatBoost confirmed_plus_synthetic/common-v2-22-features не найден в comparison report.")
        primary_path = self.comparison_dir / "catboost__confirmed_plus_synthetic.joblib"
        if not primary_path.exists():
            raise ModelRegistryError("Файл production CatBoost отсутствует.")
        def optional(name: str):
            path = self.comparison_dir / name
            return joblib.load(path) if path.exists() else None
        return ProductionModels(
            primary=joblib.load(primary_path),
            supporting_logreg=optional("logistic_regression__confirmed_plus_synthetic.joblib"),
            supporting_hgb=optional("hist_gradient_boosting__confirmed_plus_synthetic.joblib"),
            name="CatBoost", version="synthetic-v2/confirmed_plus_synthetic/structured-only",
            feature_schema=schema["feature_schema_name"], fingerprint=expected, columns=columns,
            provenance={"comparison_report": str((comparison_csv if comparison_csv.exists() else report_path).relative_to(self.root)), "selected_result": matches[0], "registry_manifest": str(manifest_path.relative_to(self.root)) if manifest_path.exists() else None},
        )
