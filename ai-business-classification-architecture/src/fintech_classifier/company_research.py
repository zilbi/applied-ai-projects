"""Existing public-source company lookup primitives.

The module deliberately keeps the project limited to its five originally
configured public web sources.  It does not use an API, an API key, an LLM or
any CAPTCHA-bypass technique.  Callers decide when external HTTP is permitted.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

from .company_parser import CompanyLookupRequest

USER_AGENT = "Mozilla/5.0 (compatible; FintechCompanyResearch/0.2)"
FNS_URL = "https://egrul.nalog.ru/index.html"


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    label: str
    url_template: str
    manual_only: bool = False


# These are the five sources already present in the project.  Checko is used
# through its public search page, not the former API endpoint.
SOURCES = (
    SourceDefinition("fns_egrul", "ФНС ЕГРЮЛ/ЕГРИП", FNS_URL, manual_only=True),
    SourceDefinition("checko", "Checko", "https://checko.ru/search?query={inn}"),
    SourceDefinition("rusprofile", "Rusprofile", "https://www.rusprofile.ru/search?query={inn}"),
    SourceDefinition("zachestnyibiznes", "ЗаЧестныйБизнес", "https://zachestnyibiznes.ru/search?query={inn}"),
    SourceDefinition("rbc_companies", "РБК Компании", "https://companies.rbc.ru/search/?query={inn}"),
)


@dataclass
class SourceEvidence:
    source: str
    url: str
    status: str
    facts: dict[str, str] = field(default_factory=dict)
    message: str | None = None
    inn_confirmed: bool = False
    content: str | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        """Return the portable record; raw page text belongs in snapshots."""
        result = asdict(self)
        result.pop("content", None)
        return result


@dataclass
class CompanyResearchRecord:
    lookup_id: str
    inn: str | None
    status: str
    canonical_facts: dict[str, str]
    source_evidence: list[SourceEvidence]
    missing_information: list[str]

    def to_dict(self) -> dict:
        return {
            "lookup_id": self.lookup_id,
            "inn": self.inn,
            "status": self.status,
            "canonical_facts": self.canonical_facts,
            "source_evidence": [item.to_dict() for item in self.source_evidence],
            "missing_information": self.missing_information,
        }


def _fetch(url: str, timeout_seconds: int = 10) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(1_000_000).decode(charset, errors="replace")


def _plain_text(payload: str) -> str:
    payload = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", payload, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", payload))).strip()


def _one(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip(" :;,.\n") if match else None


def extract_legal_facts(payload: str, inn: str) -> dict[str, str]:
    """Conservative extraction; no field is accepted without this exact INN."""
    text = _plain_text(payload)
    if inn not in re.sub(r"\D", "", text):
        return {}
    facts = {"inn": inn}
    patterns = {
        "ogrn": r"ОГРН\s*[:№]?\s*(\d{13}|\d{15})",
        "kpp": r"КПП\s*[:№]?\s*(\d{9})",
        "address": r"(?:Юридический адрес|Адрес(?: места нахождения)?)\s*[:—-]?\s*([^.;]{10,240})",
        "legal_name": r"(?:Полное наименование|Наименование организации|Название организации)\s*[:—-]?\s*([^.;]{3,240})",
    }
    for key, pattern in patterns.items():
        value = _one(pattern, text)
        if value:
            facts[key] = value
    # Several public cards expose their legal/short name in <title> or H1,
    # rather than after a textual "Наименование" label.
    if "legal_name" not in facts:
        title = re.search(r"<title[^>]*>(.*?)</title>", payload, flags=re.I | re.S)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", payload, flags=re.I | re.S)
        candidate = _plain_text((h1.group(1) if h1 else title.group(1) if title else ""))
        candidate = re.split(r"\s+-\s+(?:Москва|г\.|ИНН\b)", candidate, maxsplit=1, flags=re.I)[0].strip()
        platform_heading = ("зачестныйбизнес", "проверка контрагента", "поиск и проверка юридических", "рбк компании")
        if candidate and len(candidate) >= 3 and not any(marker in candidate.lower() for marker in platform_heading):
            facts["legal_name"] = candidate
    return facts


def fetch_source(source: SourceDefinition, inn: str) -> SourceEvidence:
    """Fetch one existing public source.  This function is intentionally explicit.

    It performs no retries or anti-bot workarounds.  The CLI blocks reaching it
    unless the operator passes ``--confirm-external-run``.
    """
    if source.manual_only:
        return SourceEvidence(
            source.label, source.url_template, "manual_lookup_required",
            message="Официальный сервис ФНС использует интерактивный поиск/защиту; ИНН подготовлен для ручного запроса.",
        )
    url = source.url_template.format(inn=urllib.parse.quote(inn))
    try:
        payload = _fetch(url)
    except Exception as exc:  # one source must not stop the remaining sources
        return SourceEvidence(source.label, url, "unavailable", message=f"{type(exc).__name__}: {exc}")
    facts = extract_legal_facts(payload, inn)
    return SourceEvidence(
        source.label, url, "matched" if facts else "no_inn_match", facts=facts,
        message=None if facts else "Страница получена, но исходный ИНН не найден в содержимом.",
        inn_confirmed=bool(facts), content=payload,
    )


def aggregate_evidence(request: CompanyLookupRequest, evidence: list[SourceEvidence]) -> CompanyResearchRecord:
    if not request.inn:
        return CompanyResearchRecord(request.lookup_id, None, "requires_review", {}, evidence, ["Нет валидного ИНН для межисточниковой проверки."])
    confirmed = [item for item in evidence if item.status == "matched" and item.inn_confirmed]
    if not confirmed:
        return CompanyResearchRecord(request.lookup_id, request.inn, "requires_review", {}, evidence, ["Ни один из пяти источников не подтвердил ИНН."])
    canonical = {"inn": request.inn}
    conflicts: list[str] = []
    for field_name in ("legal_name", "ogrn", "kpp", "address"):
        values = {item.facts[field_name] for item in confirmed if field_name in item.facts}
        if len(values) == 1:
            canonical[field_name] = values.pop()
        elif len(values) > 1:
            conflicts.append(f"Конфликт значения {field_name} между источниками: {sorted(values)}")
    if "legal_name" not in canonical:
        conflicts.append("Источники подтвердили ИНН, но не извлекли юридическое наименование.")
    return CompanyResearchRecord(request.lookup_id, request.inn, "confirmed" if not conflicts else "requires_review", canonical, evidence, conflicts)


def research_company(request: CompanyLookupRequest) -> CompanyResearchRecord:
    evidence = [fetch_source(source, request.inn) for source in SOURCES] if request.inn else []
    return aggregate_evidence(request, evidence)
