"""Validation and persistence of the minimal one-company console input."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .normalization import clean_text
from .validation import digits, valid_account, valid_bic, valid_inn, valid_kpp

CompanySide = Literal["payer", "recipient"]


@dataclass
class ManualCompanyInput:
    company_name: str
    inn: str
    kpp: str = ""
    account: str = ""
    bank_bic: str = ""
    bank_name: str = ""
    bank_corr_account: str = ""
    company_side: CompanySide = "payer"


def validate_manual_input(entry: ManualCompanyInput) -> dict:
    fields = {
        "company_name": (entry.company_name, clean_text(entry.company_name), bool(entry.company_name.strip()), "Company name is required."),
        "inn": (entry.inn, digits(entry.inn) or "", valid_inn(entry.inn), "The tax ID checksum is invalid."),
        "kpp": (entry.kpp, digits(entry.kpp) or "", not entry.kpp.strip() or valid_kpp(entry.kpp), "The registration reason code must contain 9 digits."),
        "account": (entry.account, digits(entry.account) or "", not entry.account.strip() or valid_account(entry.account), "The settlement account has an invalid length."),
        "bank_bic": (entry.bank_bic, digits(entry.bank_bic) or "", not entry.bank_bic.strip() or valid_bic(entry.bank_bic), "The bank identifier code must contain 9 digits."),
        "bank_name": (entry.bank_name, clean_text(entry.bank_name), True, ""),
        "bank_corr_account": (entry.bank_corr_account, digits(entry.bank_corr_account) or "", not entry.bank_corr_account.strip() or valid_account(entry.bank_corr_account), "The correspondent account has an invalid length."),
    }
    details, warnings = {}, []
    for name, (raw, normalized, is_valid, message) in fields.items():
        status = "valid" if is_valid and str(raw).strip() else "empty" if not str(raw).strip() else "invalid"
        details[name] = {"raw": raw, "normalized": normalized, "status": status}
        if status == "invalid": warnings.append(message)
    if entry.company_side not in ("payer", "recipient"): warnings.append("Company side must be either payer or recipient.")
    return {"is_valid": not warnings, "company_side": entry.company_side, "fields": details, "warnings": warnings}


def persist_manual_input(store, entry: ManualCompanyInput) -> tuple[int | None, int]:
    validation = validate_manual_input(entry)
    data = asdict(entry); data["validation"] = validation
    request = {"lookup_id": "MANUAL-" + (digits(entry.inn) or "UNVERIFIED"), "inn": digits(entry.inn) if valid_inn(entry.inn) else None,
               "legal_name_candidates": [entry.company_name] if entry.company_name else [], "account_candidates": [digits(entry.account)] if digits(entry.account) else [],
               "operation_ids": [], "source_sides": [entry.company_side], "lookup_status": "manual_single_entry", "manual_input": data}
    request_id = store.import_request(request, source_file="manual_console")
    row = store.connection.execute("SELECT company_id FROM research_requests WHERE id=?", (request_id,)).fetchone()
    return (int(row[0]) if row and row[0] is not None else None), request_id
