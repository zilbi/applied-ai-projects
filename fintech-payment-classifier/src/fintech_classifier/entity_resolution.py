from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .schemas import CompanyProfile, PaymentOperation
from .validation import valid_inn


@dataclass
class CompanyGroup:
    profile: CompanyProfile
    operations: list[PaymentOperation]


def _party(operation: PaymentOperation, side: str) -> tuple[str | None, str, str | None, str | None]:
    return (getattr(operation, f"{side}_inn"), getattr(operation, f"{side}_name_normalized") or "", getattr(operation, f"{side}_account"), getattr(operation, f"{side}_kpp"))


def resolve_companies(operations: list[PaymentOperation]) -> list[CompanyGroup]:
    """Create one group per valid INN; account+name is fallback only when INN is absent."""
    members: dict[str, dict] = {}
    account_name_index: dict[tuple[str, str], str] = {}
    for operation in operations:
        for side in ("payer", "recipient"):
            inn, name, account, kpp = _party(operation, side)
            if not name and not inn:
                continue
            if valid_inn(inn):
                key, confidence, grouping_case = f"inn:{inn}", 1.0, "точное совпадение валидного ИНН"
            elif account and name:
                key = account_name_index.setdefault((account, name), f"acct:{account}:{name}")
                confidence, grouping_case = .95, "счёт и совместимое нормализованное наименование"
            else:
                key, confidence, grouping_case = f"unresolved:{operation.operation_id}:{side}", .5, "недостаточно реквизитов для автоматической группировки"
            item = members.setdefault(key, {"names": [], "inns": [], "kpps": [], "accounts": [], "ops": [], "confidence": confidence, "case": grouping_case, "warnings": []})
            if name: item["names"].append(name)
            if inn: item["inns"].append(inn)
            if kpp: item["kpps"].append(kpp)
            if account: item["accounts"].append(account)
            item["ops"].append(operation)
    groups = []
    for index, item in enumerate(members.values(), 1):
        unique_ops = list({x.operation_id: x for x in item["ops"]}.values())
        inn_set = sorted(set(item["inns"]))
        warnings = item["warnings"]
        if len([x for x in inn_set if valid_inn(x)]) > 1:
            # defensive guard; current primary key prevents this nevertheless
            warnings.append("critical_conflicting_inns")
        name = max(item["names"], key=item["names"].count, default="НЕИЗВЕСТНАЯ КОМПАНИЯ")
        profile = CompanyProfile(company_id=f"CMP-PRED-{index:04d}", canonical_name=name, inn=inn_set[0] if len(inn_set) == 1 else None,
                                 kpps=sorted(set(item["kpps"])), accounts=sorted(set(item["accounts"])), operation_ids=[x.operation_id for x in unique_ops],
                                 grouping_confidence=item["confidence"], grouping_case=item["case"], warnings=warnings)
        groups.append(CompanyGroup(profile, unique_ops))
    return groups
