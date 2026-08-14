"""Fact-only OKVED collection through the five preconfigured public sources."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .company_research import SOURCES, SourceEvidence, fetch_source
from .validation import valid_inn

OKVED_RE = re.compile(r"(?<![\d.])(\d{2}(?:\.\d{1,2}){0,2})(?![\d.])")


@dataclass
class OkvedLookupRequest:
    company_id: int | None
    inn: str
    legal_name_candidates: list[str] = field(default_factory=list)


@dataclass
class FoundOkved:
    code: str
    name: str | None
    is_primary: bool
    source: str
    url: str
    inn_confirmed: bool
    confidence: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class OkvedLookupResult:
    inn: str
    status: str
    primary_okved: FoundOkved | None
    additional_okveds: list[FoundOkved]
    source_results: list[SourceEvidence]
    conflicts: list[str]
    warnings: list[str]


def extract_okveds(payload: str | None) -> tuple[list[tuple[str, str | None, bool]], list[str]]:
    """Only labels explicitly saying 'primary' make an OKVED primary."""
    if not payload:
        return [], []
    text = re.sub(r"<[^>]+>", " ", payload)
    values: list[tuple[str, str | None, bool]] = []
    warnings: list[str] = []
    # A structured activity table is the only safe generic source of codes.
    # It prevents unrelated dates, counters and catalogue links being treated
    # as OКВЭД values just because a page contains the word "ОКВЭД".
    activity = re.search(r"(?:id=[\"']activity[\"']|Виды деятельности ОКВЭД)[\s\S]{0,20000}?(?:</section>|</table>)", payload, re.I)
    if activity:
        for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", activity.group(0), re.I):
            cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, re.I)
            if len(cells) < 2:
                continue
            code_match = OKVED_RE.search(re.sub(r"<[^>]+>", " ", cells[0]))
            if not code_match:
                continue
            name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cells[1])).strip(" :;,.\n") or None
            primary = bool(re.search(r"Основной вид деятельности", row, re.I))
            values.append((code_match.group(1), name, primary))
    # Do not scan arbitrary text after the words "Основной вид деятельности":
    # a page can contain another numeric code hundreds of characters later.
    # Primary status is accepted only from the same structured table row above.
    additional_section = re.search(r"Дополнительн(?:ые|ый)[\s\S]{0,15000}", text, re.I)
    if additional_section:
        for code in OKVED_RE.findall(additional_section.group(0)):
            if not any(value[0] == code and value[2] for value in values):
                values.append((code, None, False))
    elif not values and "ОКВЭД" in text.upper():
        warnings.append("Страница упоминает ОКВЭД, но не содержит безопасно извлекаемого списка видов деятельности.")
    return list(dict.fromkeys(values)), warnings


def lookup_okved(request: OkvedLookupRequest, *, allow_external: bool = False, store=None) -> OkvedLookupResult:
    if not valid_inn(request.inn):
        return OkvedLookupResult(request.inn, "requires_review", None, [], [], [], ["ИНН невалиден."])
    if not allow_external:
        return OkvedLookupResult(request.inn, "external_run_required", None, [], [], [], ["Сетевой запуск заблокирован без --confirm-external-run."])
    evidence: list[SourceEvidence] = []; found: list[FoundOkved] = []; warnings: list[str] = []
    request_row = store.request_for_company(request.company_id) if store and request.company_id else None
    request_id = int(request_row["id"]) if request_row else None
    for source in SOURCES:
        result = fetch_source(source, request.inn)
        evidence.append(result)
        source_result_id = None
        if store:
            source_result_id = store.record_source_result(request_id, request.company_id, source_name=result.source, input_inn=request.inn,
                source_url=result.url, request_status=result.status, inn_confirmed=result.inn_confirmed,
                warnings=[result.message] if result.message else [], content=result.content, raw_result=result.to_dict())
        if not result.inn_confirmed:
            continue
        values, parse_warnings = extract_okveds(result.content)
        warnings.extend(f"{result.source}: {warning}" for warning in parse_warnings)
        for code, name, primary in values:
            item = FoundOkved(code, name, primary, result.source, result.url, True, .8, parse_warnings)
            found.append(item)
            if store and request.company_id:
                store.add_okved(request.company_id, code, name, primary, source_result_id=source_result_id, source_name=result.source, source_url=result.url, confidence=.8)
    primaries = {item.code for item in found if item.is_primary}
    conflicts = [f"Конфликт основных ОКВЭД: {sorted(primaries)}"] if len(primaries) > 1 else []
    primary = next((item for item in found if item.is_primary), None)
    additional = [item for item in found if not item.is_primary]
    status = "found" if primary and not conflicts else "partially_found" if found else "not_found"
    if conflicts:
        status = "requires_review"
    return OkvedLookupResult(request.inn, status, primary, additional, evidence, conflicts, warnings)
