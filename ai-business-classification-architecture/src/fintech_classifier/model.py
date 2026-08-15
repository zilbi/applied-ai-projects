from __future__ import annotations

import math
from collections import Counter, defaultdict


class GaussianCompanyBaseline:
    """Small dependency-free company-level baseline; no identifiers or labels leak into features."""
    def __init__(self) -> None:
        self.classes: list[str] = []
        self.priors: dict[str, float] = {}
        self.stats: dict[str, dict[str, tuple[float, float]]] = {}

    def fit(self, rows: list[tuple[dict[str, float], str]]) -> "GaussianCompanyBaseline":
        grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
        for features, label in rows:
            if label in ("A — платёжный посредник", "B — платформа / marketplace", "Не финтех"):
                grouped[label].append(features)
        self.classes = sorted(grouped)
        total = sum(map(len, grouped.values()))
        for label, feature_rows in grouped.items():
            self.priors[label] = len(feature_rows) / max(1, total)
            self.stats[label] = {}
            for key in feature_rows[0]:
                values = [x[key] for x in feature_rows]
                mean = sum(values) / len(values)
                variance = sum((x - mean) ** 2 for x in values) / max(1, len(values) - 1)
                self.stats[label][key] = (mean, max(variance, 1e-4))
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        if not self.classes:
            return {}
        logs = {}
        for label in self.classes:
            score = math.log(max(self.priors[label], 1e-9))
            for key, value in features.items():
                mean, variance = self.stats[label].get(key, (0.0, 1.0))
                score += -.5 * (math.log(2 * math.pi * variance) + ((value - mean) ** 2 / variance))
            logs[label] = score
        ceiling = max(logs.values())
        raw = {key: math.exp(value - ceiling) for key, value in logs.items()}
        total = sum(raw.values())
        return {key: value / total for key, value in raw.items()}
