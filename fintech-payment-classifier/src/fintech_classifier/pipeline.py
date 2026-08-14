from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from .arbitration import arbitrate
from .enrichment import verify_official_site
from .entity_resolution import CompanyGroup, resolve_companies
from .export import export_predictions
from .features import build_features
from .ingestion import frame_to_operations
from .model import GaussianCompanyBaseline
from .rules import score_rules
from .schemas import CompanyProfile


class ClassificationPipeline:
    def __init__(self, online: bool = True) -> None:
        self.online = online
        self.model = GaussianCompanyBaseline()

    @staticmethod
    def _training_rows(frame: pd.DataFrame) -> list[tuple[dict[str, float], str]]:
        operations, _ = frame_to_operations(frame, "training")
        by_id: dict[str, list] = {}
        for operation, (_, row) in zip(operations, frame.iterrows()):
            company_id = row.get("gold_company_id")
            if pd.notna(company_id):
                by_id.setdefault(str(company_id), []).append(operation)
        rows = []
        for company_id, company_ops in by_id.items():
            source = frame.loc[frame["gold_company_id"].astype(str) == company_id].iloc[0]
            profile = CompanyProfile(company_id=company_id, canonical_name=str(source["gold_canonical_company_name"]),
                                     grouping_confidence=1.0, grouping_case="эталонная training-группа")
            rows.append((build_features(CompanyGroup(profile, company_ops)), str(source["gold_segment"])))
        return rows

    def fit_from_excel(self, path: str | Path) -> None:
        training = pd.read_excel(path, sheet_name="Обучение_с_ответами")
        self.model.fit(self._training_rows(training))

    @staticmethod
    def _focal_group_by_operation(groups: list[CompanyGroup]) -> dict[str, CompanyGroup]:
        """The one-row Excel response needs one company. Prefer the recurrent party in its local flow."""
        memberships: dict[str, list[CompanyGroup]] = {}
        for group in groups:
            for operation_id in group.profile.operation_ids:
                memberships.setdefault(operation_id, []).append(group)
        result = {}
        for operation_id, candidates in memberships.items():
            result[operation_id] = max(candidates, key=lambda x: (len(x.operations), x.profile.grouping_confidence, x.profile.inn is not None))
        return result

    def classify_excel(self, input_path: str | Path, output_path: str | Path) -> dict[str, dict]:
        self.fit_from_excel(input_path)
        frame = pd.read_excel(input_path, sheet_name="Классификация_без_ответов")
        operations, parse_warnings = frame_to_operations(frame, "classification")
        groups = resolve_companies(operations)
        predictions_by_group: dict[str, dict] = {}
        for group in groups:
            features = build_features(group)
            website = verify_official_site(group.profile.inn, group.profile.canonical_name, online=self.online)
            rule_scores, evidence, counter = score_rules(group, website)
            decision = arbitrate(group, features, rule_scores, self.model.predict_proba(features), evidence, counter, website)
            predictions_by_group[group.profile.company_id] = {
                "company_id": group.profile.company_id, "canonical_name": group.profile.canonical_name, "grouping_case": group.profile.grouping_case,
                "official_site": website.url, "website_evidence": "; ".join(website.evidence), "predicted_segment": decision.segment,
                "confidence": decision.confidence, "alternative_hypothesis": decision.alternative_hypothesis,
                "evidence_summary": "; ".join(decision.evidence), "counter_evidence": "; ".join(decision.counter_evidence),
                "missing_information": "; ".join(decision.missing_information), "rationale": decision.rationale,
            }
        focal = self._focal_group_by_operation(groups)
        row_predictions = {operation_id: predictions_by_group[group.profile.company_id] for operation_id, group in focal.items()}
        export_predictions(input_path, output_path, row_predictions)
        return {"operations": len(operations), "companies": len(groups), "parse_warnings": parse_warnings, "predictions": row_predictions}
