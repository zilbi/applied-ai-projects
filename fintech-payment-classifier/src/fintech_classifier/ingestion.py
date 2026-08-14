from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import pandas as pd

from .normalization import normalize_requisites
from .schemas import PaymentOperation
from .validation import valid_account, valid_bic, valid_inn, valid_kpp


HEADER_ALIASES = {
    "operation_id": {"operation_id", "id операции", "номер операции", "id"},
    "operation_datetime": {"operation_datetime", "дата операции", "дата", "datetime", "дата время"},
    "amount": {"amount", "сумма", "сумма операции"},
    "currency": {"currency", "валюта"},
    "direction": {"direction", "направление", "тип операции"},
    "payment_purpose_raw": {"payment_purpose_raw", "назначение платежа", "назначение"},
}
for side, ru in (("payer", "плательщик"), ("recipient", "получатель")):
    HEADER_ALIASES |= {
        f"{side}_name_raw": {f"{side}_name_raw", f"{ru}", f"наименование {ru}оста"},
        f"{side}_inn": {f"{side}_inn", f"инн {ru}а", f"инн {ru}я"},
        f"{side}_kpp": {f"{side}_kpp", f"кпп {ru}а", f"кпп {ru}я"},
        f"{side}_account": {f"{side}_account", f"счет {ru}а", f"счёт {ru}а", f"расчетный счет {ru}а"},
        f"{side}_bic": {f"{side}_bic", f"бик {ru}а"},
        f"{side}_bank_name": {f"{side}_bank_name", f"банк {ru}а"},
        f"{side}_corr_account": {f"{side}_corr_account", f"корр счет {ru}а", f"корр счёт {ru}а"},
    }


def _header_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    lookup = {alias: target for target, aliases in HEADER_ALIASES.items() for alias in aliases}
    renamed = {column: lookup.get(_header_key(column), str(column)) for column in frame.columns}
    return frame.rename(columns=renamed)


def _to_decimal(value: object) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _to_datetime(value: object) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.to_pydatetime()


def _operation_from_record(record: dict, row_number: int, source_id: str) -> PaymentOperation:
    normalized = normalize_requisites(record)
    warnings: list[str] = []
    for side in ("payer", "recipient"):
        checks = (("inn", valid_inn), ("kpp", valid_kpp), ("account", valid_account), ("bic", valid_bic))
        for field, validator in checks:
            value = normalized.get(f"{side}_{field}")
            if value and not validator(value):
                warnings.append(f"invalid_{side}_{field}")
    amount = _to_decimal(normalized.get("amount"))
    if normalized.get("amount") not in (None, "") and amount is None:
        warnings.append("invalid_amount")
    direction = str(normalized.get("direction") or "").upper()
    if direction in {"IN", "ВХОДЯЩИЙ", "ПОСТУПЛЕНИЕ"}:
        direction = "IN"
    elif direction in {"OUT", "ИСХОДЯЩИЙ", "СПИСАНИЕ"}:
        direction = "OUT"
    else:
        direction = None
        warnings.append("missing_or_invalid_direction")
    operation_id = str(normalized.get("operation_id") or f"{source_id}-{row_number}")
    values = {key: normalized.get(key) for key in PaymentOperation.model_fields}
    values.update(operation_id=operation_id, operation_datetime=_to_datetime(normalized.get("operation_datetime")), amount=amount,
                  currency=str(normalized.get("currency") or "RUB").upper(), direction=direction, source_id=str(normalized.get("source_id") or source_id), parse_warnings=warnings)
    return PaymentOperation(**values)


def frame_to_operations(frame: pd.DataFrame, source_id: str) -> tuple[list[PaymentOperation], list[str]]:
    frame = canonicalize_columns(frame)
    operations: list[PaymentOperation] = []
    warnings: list[str] = []
    for index, row in frame.iterrows():
        try:
            operations.append(_operation_from_record(row.where(pd.notna(row), None).to_dict(), int(index) + 2, source_id))
        except Exception as exc:  # one row must never stop a file
            warnings.append(f"row_{int(index) + 2}: {exc}")
    return operations, warnings


def read_xlsx(path: str | Path, sheet_name: str | int = 0) -> tuple[list[PaymentOperation], list[str]]:
    return frame_to_operations(pd.read_excel(path, sheet_name=sheet_name), Path(path).stem)


def read_csv(path: str | Path) -> tuple[list[PaymentOperation], list[str]]:
    raw = Path(path).read_bytes()
    encoding = next((x for x in ("utf-8-sig", "cp1251", "utf-8") if _decodable(raw, x)), "utf-8")
    sample = raw[:8192].decode(encoding, errors="replace")
    delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    return frame_to_operations(pd.read_csv(io.BytesIO(raw), encoding=encoding, sep=delimiter), Path(path).stem)


def _decodable(raw: bytes, encoding: str) -> bool:
    try:
        raw.decode(encoding)
        return True
    except UnicodeDecodeError:
        return False


def read_json_api(payload: str | bytes | dict | list, source_id: str = "json_api") -> tuple[list[PaymentOperation], list[str]]:
    parsed = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    rows = parsed.get("operations", parsed.get("data", [])) if isinstance(parsed, dict) else parsed
    return frame_to_operations(pd.json_normalize(rows), source_id)


def read_mt940(text: str, source_id: str = "mt940") -> tuple[list[PaymentOperation], list[str]]:
    operations, warnings, current = [], [], {}
    for line in text.splitlines():
        if line.startswith(":61:"):
            if current:
                operations.append(_operation_from_record(current, len(operations) + 1, source_id))
            body = line[4:]
            match = re.match(r"(\d{6})(?:\d{4})?([CD])([\d,]+)", body)
            current = {"operation_id": f"{source_id}-{len(operations)+1}", "direction": "OUT" if match and match.group(2) == "D" else "IN"}
            if match:
                current.update(operation_datetime=datetime.strptime(match.group(1), "%y%m%d"), amount=match.group(3).replace(",", "."))
            else:
                warnings.append(f"unparsed :61: {line}")
        elif line.startswith(":86:"):
            current["payment_purpose_raw"] = (current.get("payment_purpose_raw", "") + " " + line[4:]).strip()
    if current:
        operations.append(_operation_from_record(current, len(operations) + 1, source_id))
    return operations, warnings


def read_1c(text: str, source_id: str = "1c") -> tuple[list[PaymentOperation], list[str]]:
    records, current, warnings = [], None, []
    aliases = {"Плательщик": "payer_name_raw", "ИННПлательщика": "payer_inn", "СчетПлательщика": "payer_account", "Получатель": "recipient_name_raw", "ИННПолучателя": "recipient_inn", "СчетПолучателя": "recipient_account", "Сумма": "amount", "НазначениеПлатежа": "payment_purpose_raw", "Дата": "operation_datetime"}
    for line in text.splitlines():
        line = line.strip()
        if line == "СекцияДокумент": current = {}
        elif line == "КонецДокумента" and current is not None:
            records.append(current); current = None
        elif current is not None and "=" in line:
            key, value = line.split("=", 1); current[aliases.get(key, key)] = value
    return frame_to_operations(pd.DataFrame(records), source_id)
