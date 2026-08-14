"""Reproducible synthetic transaction-time profiles.

This module is intentionally limited to creating a *derived* demonstration
dataset.  The source workbook is never modified.  Profiles are behavioural
hypotheses, not evidence about a real company's customers, and therefore must
not be presented as observed payment behaviour.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from random import Random
import re
from typing import Iterable, Mapping


PROFILE_A = "A"
PROFILE_B = "B"
PROFILE_NON_FINTECH = "NON_FINTECH"
PROFILE_REVIEW = "REVIEW"

# The probabilities are deliberately overlapping.  Time is only one weak
# behavioural signal, never a class definition.
PROFILES: Mapping[str, dict[str, object]] = {
    PROFILE_A: {
        "weekend_probability": 0.28,
        # Payment/settlement infrastructure: can run overnight, with no sharp
        # business-hours-only restriction.
        "hour_weights": (0.06, 0.05, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03,
                         0.035, 0.04, 0.045, 0.045, 0.045, 0.045, 0.045,
                         0.045, 0.045, 0.05, 0.055, 0.06, 0.06, 0.055,
                         0.05, 0.05),
    },
    PROFILE_B: {
        "weekend_probability": 0.43,
        # Consumer marketplace/platform: intentionally stronger evening and
        # weekend activity, but still has daytime orders and settlements.
        "hour_weights": (0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.02,
                         0.03, 0.025, 0.025, 0.03, 0.03, 0.03, 0.03, 0.03,
                         0.03, 0.04, 0.10, 0.11, 0.11, 0.10, 0.10, 0.09),
    },
    PROFILE_NON_FINTECH: {
        "weekend_probability": 0.07,
        # Ordinary B2B / own-goods and services: mainly weekday working hours
        # with a modest early-evening tail.
        "hour_weights": (0.002, 0.002, 0.002, 0.002, 0.002, 0.003, 0.004,
                         0.008, 0.035, 0.07, 0.10, 0.115, 0.105, 0.10, 0.10,
                         0.095, 0.08, 0.055, 0.035, 0.02, 0.012, 0.008,
                         0.005, 0.003),
    },
    PROFILE_REVIEW: {
        "weekend_probability": 2 / 7,
        "hour_weights": tuple(1 / 24 for _ in range(24)),
    },
}

_TARGETS = {
    "платёжный посредник": PROFILE_A,
    "платежный посредник": PROFILE_A,
    "платформа / marketplace": PROFILE_B,
    "платформа": PROFILE_B,
    "marketplace": PROFILE_B,
    "non_fintech": PROFILE_NON_FINTECH,
    "не финтех": PROFILE_NON_FINTECH,
    "нефинтех": PROFILE_NON_FINTECH,
    "review": PROFILE_REVIEW,
    "требует проверки": PROFILE_REVIEW,
}


def profile_from_target(value: object) -> str:
    """Normalize the known training label to an internal time profile."""
    text = re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()
    # Latin one-letter labels must be checked as tokens; substring matching
    # would incorrectly classify ``marketplace`` as A.
    if re.match(r"^a(?:\s|—|-|$)", text):
        return PROFILE_A
    if re.match(r"^b(?:\s|—|-|$)", text):
        return PROFILE_B
    for marker, profile in _TARGETS.items():
        if marker in text:
            return profile
    return PROFILE_REVIEW


def profile_from_operation_text(record: Mapping[str, object]) -> str:
    """Infer a neutral test-time profile from operation semantics only.

    This does *not* read predicted classes, IDs, INNs or a hidden label.  The
    result stays in the generation report and is never put into the workbook.
    """
    text = " ".join(str(record.get(key) or "") for key in (
        "payment_purpose_raw", "payment_purpose_normalized", "company_role_in_operation",
    )).lower().replace("ё", "е")
    platform = sum(marker in text for marker in (
        "заказ", "order", "продав", "исполн", "платформ", "marketplace", "курьер", "доставк",
    ))
    payment = sum(marker in text for marker in (
        "эквайр", "мерчант", "платеж", "платеж", "процессинг", "реестр", "settlement", "payout",
    ))
    ordinary = sum(marker in text for marker in (
        "собствен", "товар", "хозяйствен", "аренд", "закуп", "поставк", "услуг",
    ))
    if platform >= 2 or (platform >= 1 and platform > payment):
        return PROFILE_B
    if payment >= 2 or (payment >= 1 and payment > ordinary):
        return PROFILE_A
    if ordinary:
        return PROFILE_NON_FINTECH
    return PROFILE_REVIEW


def _weighted_hour(rng: Random, weights: tuple[float, ...]) -> int:
    point = rng.random() * sum(weights)
    subtotal = 0.0
    for hour, weight in enumerate(weights):
        subtotal += weight
        if point <= subtotal:
            return hour
    return 23


def _date_with_weekend_probability(rng: Random, start: datetime, end: datetime, probability: float) -> datetime:
    wanted_weekend = rng.random() < probability
    days = (end.date() - start.date()).days
    candidates = [start + timedelta(days=offset) for offset in range(days + 1)
                  if ((start + timedelta(days=offset)).weekday() >= 5) == wanted_weekend]
    return candidates[rng.randrange(len(candidates))]


def synthetic_datetime(*, operation_id: object, profile: str, seed: int,
                       start: datetime = datetime(2026, 3, 1),
                       end: datetime = datetime(2026, 6, 30)) -> datetime:
    """Return a stable Moscow-local naive datetime for one operation."""
    settings = PROFILES.get(profile, PROFILES[PROFILE_REVIEW])
    rng = Random(f"{seed}:{operation_id}:{profile}")
    day = _date_with_weekend_probability(rng, start, end, float(settings["weekend_probability"]))
    hour = _weighted_hour(rng, tuple(settings["hour_weights"]))
    return day.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60), microsecond=0)


def temporal_behavior_features(values: Iterable[datetime | None]) -> dict[str, float]:
    """Aggregate timestamps to weak, company-level behavioural features.

    No calendar date, operation identifier or individual time is returned, so
    the classifier cannot memorise a company through a timestamp value.
    """
    items = [value for value in values if isinstance(value, datetime)]
    n = len(items)
    if not n:
        return {
            "datetime_data_available": 0.0,
            "weekend_share": 0.0,
            "evening_share_18_23": 0.0,
            "business_hours_share_08_18": 0.0,
            "overnight_share_00_06": 0.0,
        }
    return {
        "datetime_data_available": 1.0,
        "weekend_share": round(sum(value.weekday() >= 5 for value in items) / n, 6),
        "evening_share_18_23": round(sum(value.hour >= 18 for value in items) / n, 6),
        "business_hours_share_08_18": round(sum(8 <= value.hour < 18 for value in items) / n, 6),
        "overnight_share_00_06": round(sum(value.hour < 6 for value in items) / n, 6),
    }
