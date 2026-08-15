from __future__ import annotations

from .schemas import Decision, WebsiteResult

REVIEW = "Требует проверки"


def arbitrate(group, features: dict[str, float], rule_scores: dict[str, float], model_scores: dict[str, float], evidence: dict[str, list[str]], counter: dict[str, list[str]], website: WebsiteResult) -> Decision:
    labels = tuple(rule_scores)
    final = {label: .70 * rule_scores.get(label, 0) + .20 * model_scores.get(label, 0) + .10 * features["data_quality"] for label in labels}
    ordered = sorted(final, key=final.get, reverse=True)
    winner, runner_up = ordered[0], ordered[1]
    raw_confidence = final[winner] * group.profile.grouping_confidence * (0.92 if not website.url else 1.0)
    missing = list(group.profile.warnings)
    if not website.url: missing.append("официальный сайт не подтверждён")
    if not features["has_two_sided_flow"]: missing.append("наблюдается только одна сторона денежного потока")
    gap = final[winner] - final[runner_up]
    conflicting = rule_scores["A — платёжный посредник"] >= .45 and rule_scores["B — платформа / marketplace"] >= .45
    review = (features["operations"] < 5 and not website.url) or not website.url or gap < .15 or raw_confidence < .65 or conflicting or bool(group.profile.warnings)
    if review:
        reasons = ["недостаточно независимых подтверждений для автоматического решения"] + missing
        rationale = "; ".join(dict.fromkeys(reasons)) + "."
        return Decision(segment=REVIEW, confidence=round(min(raw_confidence, .64), 2), alternative_hypothesis=winner,
                        evidence=(evidence[winner] + [f"ML baseline: {model_scores.get(winner, 0):.2f}"])[:7], counter_evidence=counter[winner][:5], missing_information=list(dict.fromkeys(missing)), rationale=rationale)
    rationale = f"Компания отнесена к «{winner}»: " + "; ".join(evidence[winner][:3]) + "."
    return Decision(segment=winner, confidence=round(raw_confidence, 2), alternative_hypothesis=runner_up,
                    evidence=(evidence[winner] + website.evidence)[:7], counter_evidence=counter[winner][:5], missing_information=missing, rationale=rationale)
