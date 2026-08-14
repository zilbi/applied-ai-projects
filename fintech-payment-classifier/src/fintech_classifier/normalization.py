from __future__ import annotations

import re
import unicodedata

from .validation import digits

LEGAL_FORMS = re.compile(r"\b(ООО|АО|ПАО|ЗАО|НАО|ИП|КБ|БАНК|ГК|ФГУП|МУП)\b", re.I)
SPACE = re.compile(r"\s+")
PUNCT = re.compile(r"[^0-9A-ZА-ЯЁ]+", re.I)


def clean_text(value: object | None) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value)).replace("Ё", "Е").replace("ё", "е")
    return SPACE.sub(" ", value).strip()


def normalize_name(value: object | None) -> str:
    value = clean_text(value).upper().replace("«", " ").replace("»", " ").replace('"', " ")
    value = LEGAL_FORMS.sub(" ", value)
    return SPACE.sub(" ", PUNCT.sub(" ", value)).strip()


def normalize_purpose(value: object | None) -> str:
    return SPACE.sub(" ", PUNCT.sub(" ", clean_text(value).upper())).strip()


def normalize_requisites(record: dict) -> dict:
    result = dict(record)
    for side in ("payer", "recipient"):
        raw = result.get(f"{side}_name_raw") or result.get(f"{side}_name_normalized")
        result[f"{side}_name_normalized"] = normalize_name(raw)
        for field in ("inn", "kpp", "account", "bic", "corr_account"):
            result[f"{side}_{field}"] = digits(result.get(f"{side}_{field}"))
    raw_purpose = result.get("payment_purpose_raw") or result.get("payment_purpose_normalized")
    result["payment_purpose_normalized"] = normalize_purpose(raw_purpose)
    return result
