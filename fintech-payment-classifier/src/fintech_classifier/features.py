from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from statistics import median

from .entity_resolution import CompanyGroup

A_MARKERS = ("ЭКВАЙРИНГ", "PROCESSING", "MERCHANT", "ТЕРМИНАЛ", "КОМИСС", "ПЛАТЕЖНЫЙ ШЛЮЗ", "РЕЕСТР", "SPLIT", "PAYOUT", "ПРИЕМ ПЛАТЕЖ", "ПРИЁМ ПЛАТЕЖ")
B_MARKERS = ("АГЕНТ", "ПРИНЦИПАЛ", "ПРОДАВЕЦ", "ИСПОЛНИТЕЛ", "КУРЬЕР", "АВТОР", "MARKETPLACE", "ЗАКАЗ", "ДОСТАВК", "РАЗМЕЩЕНИ", "ПОДПИСК", "SELLER", "PERFORMER")
NON_FINTECH_MARKERS = ("СОБСТВЕНН", "ТОВАР", "УСЛУГ", "АРЕНД", "МЕДИЦ", "ОБУЧЕН", "РЕСТОРАН", "ТРАНСПОРТ", "НАЛОГ", "ПОСТАВЩИК")
ID_MARKERS = ("ORDER", "SELLER", "MERCHANT", "REGISTER", "PAYOUT", "PERFORMER")


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _amount(operation) -> float:
    return float(operation.amount or 0)


def build_features(group: CompanyGroup) -> dict[str, float]:
    ops = group.operations
    in_ops = [x for x in ops if x.direction == "IN"]
    out_ops = [x for x in ops if x.direction == "OUT"]
    amounts = [_amount(x) for x in ops if x.amount is not None]
    in_amounts, out_amounts = [_amount(x) for x in in_ops], [_amount(x) for x in out_ops]
    purposes = [x.payment_purpose_normalized or "" for x in ops]
    joined = " ".join(purposes)
    payer_names = [x.payer_name_normalized for x in ops if x.payer_name_normalized and x.payer_inn != group.profile.inn]
    recipient_names = [x.recipient_name_normalized for x in ops if x.recipient_name_normalized and x.recipient_inn != group.profile.inn]
    counterparties = payer_names + recipient_names
    counts = Counter(counterparties)
    turnover = sum(amounts)
    hhi = sum((count / max(1, len(counterparties))) ** 2 for count in counts.values())
    dated = sorted(x.operation_datetime for x in ops if x.operation_datetime)
    gaps = [(later - earlier).total_seconds() / 3600 for earlier, later in zip(dated, dated[1:])]
    id_hits = sum(_has_marker(x, ID_MARKERS) for x in purposes)
    fee_hits = sum("КОМИСС" in x for x in purposes)
    matched_net_settlements = _net_settlement_ratio(in_ops, out_ops)
    return {
        "operations": float(len(ops)), "in_count": float(len(in_ops)), "out_count": float(len(out_ops)),
        "in_share": len(in_ops) / max(1, len(ops)), "out_share": len(out_ops) / max(1, len(ops)),
        "turnover_log": math.log1p(turnover), "in_turnover_share": sum(in_amounts) / max(1, sum(in_amounts) + sum(out_amounts)),
        "mean_amount_log": math.log1p(sum(amounts) / max(1, len(amounts))), "median_amount_log": math.log1p(median(amounts) if amounts else 0),
        "counterparties": float(len(counts)), "counterparty_hhi": hhi, "repeat_counterparty_share": sum(v > 1 for v in counts.values()) / max(1, len(counts)),
        "median_gap_hours": median(gaps) if gaps else 0.0, "a_marker_share": sum(_has_marker(x, A_MARKERS) for x in purposes) / max(1, len(purposes)),
        "b_marker_share": sum(_has_marker(x, B_MARKERS) for x in purposes) / max(1, len(purposes)),
        "non_fintech_marker_share": sum(_has_marker(x, NON_FINTECH_MARKERS) for x in purposes) / max(1, len(purposes)),
        "identifier_share": id_hits / max(1, len(purposes)), "fee_share": fee_hits / max(1, len(purposes)),
        "net_settlement_ratio": matched_net_settlements, "has_two_sided_flow": float(bool(in_ops and out_ops)),
        "data_quality": _data_quality(group),
    }


def _net_settlement_ratio(in_ops: list, out_ops: list) -> float:
    """Fraction of outgoing amounts explainable by prior inflows after 1–5% fee."""
    if not in_ops or not out_ops:
        return 0.0
    incoming = sorted(in_ops, key=lambda x: x.operation_datetime or datetime.min)
    matches = 0
    for outgoing in out_ops:
        candidates = [x for x in incoming if not outgoing.operation_datetime or not x.operation_datetime or x.operation_datetime <= outgoing.operation_datetime]
        target = _amount(outgoing)
        # one-to-one and many-to-one registry approximation
        for candidate in candidates:
            ratio = target / max(.01, _amount(candidate))
            if .94 <= ratio <= 1.01:
                matches += 1; break
        else:
            for size in (2, 3, 4):
                subtotal = sum(_amount(x) for x in candidates[-size:])
                if subtotal and .94 <= target / subtotal <= 1.01:
                    matches += 1; break
    return matches / max(1, len(out_ops))


def _data_quality(group: CompanyGroup) -> float:
    ops = group.operations
    complete = sum(bool(x.amount is not None and x.direction and x.operation_datetime) for x in ops) / max(1, len(ops))
    has_identity = 1.0 if group.profile.inn else .55 if group.profile.accounts else .2
    return round(.65 * complete + .35 * has_identity, 4)


def representative_purposes(group: CompanyGroup, limit: int = 12) -> list[str]:
    purposes = [x.payment_purpose_raw or x.payment_purpose_normalized or "" for x in group.operations]
    return [value for value, _ in Counter(purposes).most_common(limit) if value]
