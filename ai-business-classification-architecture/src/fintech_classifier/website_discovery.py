"""Deterministic, brand-first discovery and verification of company sites.

Search is deliberately separated from identity verification.  A registry card
may prove a legal entity exists, but its domain is never treated as that
entity's official public site.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

from . import enrichment
from .normalization import clean_text
from .validation import valid_inn
from .website_analyzer import MAX_SUBPAGES, select_relevant_links
from .website_domain_roles import DomainRole, HARD_REJECT_ROLES, classify_domain_role as _classify_domain_role

DIRECTORY_WORDS = ("проверка контрагентов", "справочник организаций", "отзывы о компаниях", "вакансии", "государственный реестр")
CAREER_WORDS = ("ваканси", "стажировк", "карьер", "подать заявку", "присоединиться к команде", "работа в")
_CYRILLIC = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


@dataclass
class WebsiteDiscoveryRequest:
    company_id: int
    inn: str | None
    kpp: str | None = None
    confirmed_legal_name: str | None = None
    company_aliases: list[str] = field(default_factory=list)
    ogrn: str | None = None
    legal_address: str | None = None
    region: str | None = None
    primary_okved: str | None = None
    additional_okveds: list[str] = field(default_factory=list)
    brand_name: str | None = None
    short_name: str | None = None


@dataclass
class WebsiteCandidate:
    candidate_url: str
    domain: str
    search_query: str
    search_position: int | None = None
    search_title: str | None = None
    search_snippet: str | None = None
    candidate_source: str | None = None
    source_type: str = "search_result"
    domain_role: str = DomainRole.OFFICIAL_CANDIDATE.value
    role_reason: str | None = None
    brand_match: bool = False
    title_match: bool = False
    rejection_reason: str | None = None
    selected: bool = False
    search_score: float = 0.0
    verification_score: float = 0.0
    candidate_score: float = 0.0  # total score, retained for legacy reports
    candidate_status: str = "candidate"
    positive_evidence: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    checked_pages: list[str] = field(default_factory=list)
    matched_inn: str | None = None
    matched_legal_name: bool = False
    matched_kpp: bool = False
    matched_address: bool = False
    discovery_status: str = "found"
    verification_status: str = "not_started"
    fetch_status: str = "not_started"
    analysis_status: str = "not_started"
    registry_sources: list[str] = field(default_factory=list)
    # The following fields make every stage auditable.  They deliberately do
    # not rely on a successful HTTP request: a found but unavailable domain is
    # still a candidate, while a directory card is rejected before fetch.
    hard_rejected: bool = False
    shortlist_eligible: bool = False
    selection_status: str = "NOT_CHECKED"
    score_components: dict[str, float] = field(default_factory=dict)
    identity_evidence_scope: str = "UNKNOWN"


def classify_domain_role(url: str, target_company: WebsiteDiscoveryRequest | None = None,
                         *, title: str | None = None, snippet: str | None = None) -> DomainRole:
    """Compatibility wrapper around the central role taxonomy."""
    return _classify_domain_role(url, title=title, snippet=snippet)[0]


def _tokens(value: str | None) -> set[str]:
    ignored = {"ооо", "ао", "пао", "зао", "нао", "ип", "компания", "банк", "общество", "ограниченной", "ответственностью", "ру"}
    return {word for word in re.findall(r"[а-яёa-z0-9]{3,}", clean_text(value or "").lower()) if word not in ignored}


def _latin(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value or "").lower().translate(_CYRILLIC))


def _brand(request: WebsiteDiscoveryRequest) -> str:
    explicit = clean_text(request.brand_name or request.short_name or "")
    if explicit:
        return explicit
    legal = clean_text(request.confirmed_legal_name or "")
    aliases = [clean_text(item) for item in request.company_aliases if clean_text(item)]
    # Operation-level aliases are ordered by observed frequency by the caller.
    # Prefer a clean short commercial name, but never a trailing one-letter
    # typo or the payment-system suffix ``RUS``.
    legal_forms = {"ооо", "ао", "пао", "зао", "нао", "ип", "фгбо", "гбу"}
    public = []
    for position, item in enumerate(aliases):
        raw_tokens = clean_text(item).split()
        tokens = [token.lower() for token in raw_tokens]
        if not tokens or clean_text(item).lower() == legal.lower():
            continue
        without_form = [token for token in tokens if token not in legal_forms]
        if not without_form:
            continue
        penalty = 0
        if without_form[-1] in {"rus", "р"} or clean_text(item).lower().endswith(".р"):
            penalty += 100
        # Do not choose a clipped one-letter tail such as ``ВсеИнструменты р``.
        if len(without_form) > 1 and len(without_form[-1]) == 1:
            penalty += 100
        display = " ".join(token for token in raw_tokens if token.lower() not in legal_forms)
        public.append((penalty, len(" ".join(without_form)), position, display))
    if public:
        return min(public)[-1]
    fallback = min(aliases or [legal], key=len, default="")
    stripped = " ".join(token for token in clean_text(fallback).split() if token.lower() not in legal_forms)
    return stripped or fallback


def discovery_query_plan(request: WebsiteDiscoveryRequest) -> tuple[str, str]:
    """Return the two brand-only queries; identifiers never enter discovery."""
    brand = _brand(request)
    if not brand:
        return "", ""
    return brand, f"{brand} официальный сайт"


def build_queries(request: WebsiteDiscoveryRequest) -> list[str]:
    return list(dict.fromkeys(query for query in discovery_query_plan(request) if query))


def _page_text(payload: str) -> str:
    payload = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", payload, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", payload))).strip()


def _is_career_page(payload: str) -> bool:
    """Reject a recruitment microsite even if it uses the employer's brand."""
    text = clean_text(payload).lower()
    return sum(marker in text for marker in CAREER_WORDS) >= 2


def _page_is_directory(domain: str, text: str) -> bool:
    if classify_domain_role(domain) in HARD_REJECT_ROLES:
        return True
    lowered_text = text.lower()
    return sum(marker in lowered_text for marker in DIRECTORY_WORDS) >= 2


def normalize_candidate_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    host = parsed.netloc.lower()
    if not host:
        return ""
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = urllib.parse.urlencode([(key, val) for key, val in pairs if not key.lower().startswith(("utm_", "yclid", "gclid"))])
    return urllib.parse.urlunsplit((scheme, host, parsed.path or "", query, ""))


def registrable_domain(value: str) -> str:
    """Stable merge key for the public domain without tracking identifiers.

    A dependency-free implementation is sufficient for the Russian/company
    domains handled here: it eliminates presentation-only ``www.``/``m.``
    aliases and keeps the final two labels.  The original URL is retained as
    provenance and is never replaced by this key.
    """
    host = urllib.parse.urlsplit(value if "://" in value else "https://" + value).netloc.lower().split(":")[0]
    host = re.sub(r"^(?:www|m)\.", "", host)
    parts = [part for part in host.split(".") if part]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _fetch_status(detail: str) -> str:
    value = detail.lower()
    if "blocked_by_waf" in value or "interstitial" in value:
        return "blocked_by_waf"
    if "invalid_content_type" in value or "non-html" in value:
        return "invalid_content_type"
    if "timed out" in value or "timeout" in value:
        return "timeout"
    for code in (401, 403, 404, 498):
        if f"{code}" in value:
            return f"http_{code}"
    if "connect" in value or "dns" in value or "urlerror" in value:
        return "connection_error"
    return "error"


def _legacy_status(candidate: WebsiteCandidate) -> str:
    if candidate.verification_status.startswith("confirmed"):
        return "confirmed"
    if candidate.verification_status == "rejected":
        return "rejected"
    if candidate.fetch_status not in {"not_started", "success"}:
        return "unavailable"
    if candidate.verification_status in {"probable", "requires_review"}:
        return "requires_review"
    return "candidate"


def _all_valid_inns(text: str) -> set[str]:
    return {value for value in re.findall(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)", re.sub(r"\s+", "", text)) if valid_inn(value)}


def _compatible_name(page_text: str, legal_name: str | None) -> bool:
    tokens = _tokens(legal_name)
    return bool(tokens) and len(tokens & _tokens(page_text)) / len(tokens) >= 0.7


def _brand_in_domain(request: WebsiteDiscoveryRequest, domain: str) -> bool:
    labels = re.sub(r"^(www|m)\.", "", domain.lower()).split(".")[:-1]
    # Exact label comparison deliberately avoids accepting ``mkb-10.com``
    # as an official site for the short brand ``МКБ``.  We do allow a common
    # transliterated spelling of a Cyrillic commercial brand.
    return bool(_brand_domain_variants(request) & {_latin(label) for label in labels})


def _brand_domain_variants(request: WebsiteDiscoveryRequest) -> set[str]:
    raw = clean_text(_brand(request)).lower()
    raw = re.sub(r"^www\.", "", raw)
    raw = re.sub(r"\.(?:ru|ру|рф|com|net)$", "", raw)
    compact = _latin(raw)
    values = {compact} if len(compact) >= 3 else set()
    # Russian transliteration frequently alternates terminal ``-y``/``-i``.
    if compact.endswith("y"):
        values.add(compact[:-1] + "i")
    return values


def _brand_in_text(request: WebsiteDiscoveryRequest, text: str | None) -> bool:
    brand_tokens = _tokens(_brand(request))
    return bool(brand_tokens) and len(brand_tokens & _tokens(text)) / len(brand_tokens) >= 0.7


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def calculate_search_components(request: WebsiteDiscoveryRequest, candidate: WebsiteCandidate) -> dict[str, float]:
    """Calculate search-only components without mutating evidence or score.

    Candidates are merged before this function is called by the workflow.
    Keeping the calculation pure prevents repeated Tavily/registry provenance
    from inflating either the score or the human-readable evidence.
    """
    components: dict[str, float] = {}
    candidate.brand_match = _brand_in_domain(request, candidate.domain)
    title_match = _brand_in_text(request, candidate.search_title)
    snippet_match = _brand_in_text(request, candidate.search_snippet)
    candidate.title_match = title_match
    if candidate.brand_match:
        components["exact_brand_domain"] = 40
    if title_match:
        components["title_brand_match"] = 25
    elif snippet_match:
        components["snippet_brand_match"] = 15
    if candidate.search_position == 1:
        components["search_position"] = 15
    elif candidate.search_position == 2:
        components["search_position"] = 10
    elif candidate.search_position == 3:
        components["search_position"] = 5
    if urllib.parse.urlsplit(candidate.candidate_url).path in {"", "/"}:
        components["root_url"] = 5
    if candidate.registry_sources:
        components["registry_reported"] = 10
    suffix = candidate.domain.rsplit(".", 1)[-1]
    if suffix in {"ru", "рф"}:
        components["local_domain_suffix"] = 8
    elif len(suffix) == 2:
        # A neighbouring country storefront can have a perfect brand label,
        # but it is weaker than the Russian public domain for a Russian INN.
        components["foreign_country_suffix"] = -15
    if candidate.domain_role == DomainRole.PROJECT_OR_EVENT.value:
        components["project_penalty"] = -50
    return components


def _component_evidence(components: dict[str, float]) -> list[str]:
    labels = {
        "exact_brand_domain": "домен совпадает с брендом (+40)",
        "title_brand_match": "заголовок результата совпадает с брендом (+25)",
        "snippet_brand_match": "сниппет совпадает с брендом (+15)",
        "root_url": "корневой URL домена (+5)",
        "registry_reported": "домен указан в реестровом источнике (+10)",
        "project_penalty": "страница проекта/мероприятия (−50)",
        "local_domain_suffix": "российская доменная зона (+8)",
        "foreign_country_suffix": "зарубежная страновая версия домена (−15)",
    }
    output = []
    for key, value in components.items():
        if key == "search_position":
            output.append(f"позиция {int(value and {15: 1, 10: 2, 5: 3}.get(value, 0))} в выдаче (+{int(value)})")
        elif key in labels:
            output.append(labels[key])
    return output


def rescore_candidate(request: WebsiteDiscoveryRequest, candidate: WebsiteCandidate) -> WebsiteCandidate:
    """Idempotently reset and recalculate the post-merge candidate score."""
    source_evidence = [item for item in candidate.positive_evidence if "(+" not in item and "(−" not in item]
    candidate.score_components = calculate_search_components(request, candidate)
    candidate.search_score = round(sum(candidate.score_components.values()), 2)
    candidate.candidate_score = round(candidate.search_score + candidate.verification_score, 2)
    candidate.positive_evidence = _unique(source_evidence + _component_evidence(candidate.score_components))
    candidate.negative_evidence = _unique(candidate.negative_evidence)
    candidate.shortlist_eligible = is_eligible_for_verification(candidate)
    return candidate


ALLOWED_VERIFICATION_ROLES = {DomainRole.OFFICIAL_CANDIDATE.value}


def is_eligible_for_verification(candidate: WebsiteCandidate) -> bool:
    """Strict no-fetch gate applied before any page is opened."""
    if candidate.hard_rejected or candidate.domain_role not in ALLOWED_VERIFICATION_ROLES:
        return False
    if candidate.brand_match:
        return True
    if candidate.candidate_score >= 40:
        return True
    return candidate.source_type == "registry_reported_website" and candidate.domain_role == DomainRole.OFFICIAL_CANDIDATE.value


def _candidate_is_viable(candidate: WebsiteCandidate) -> bool:
    """A selectable site needs an official role and brand/registry linkage."""
    if not candidate.shortlist_eligible or candidate.hard_rejected or candidate.domain_role not in ALLOWED_VERIFICATION_ROLES or candidate.verification_status == "rejected":
        return False
    return candidate.verification_status in {"confirmed_by_website", "confirmed_by_registry", "probable"}


def brand_domain_hypotheses(request: WebsiteDiscoveryRequest) -> list[str]:
    """Small last-resort set of brand domains; never a confirmation itself."""
    brand = _latin(_brand(request))
    if len(brand) < 3:
        return []
    for suffix in ("rus", "ru"):
        if brand.endswith(suffix) and len(brand) > len(suffix) + 3:
            brand = brand[:-len(suffix)]
            break
    variants = [brand]
    # Russian transliteration has common ``-y``/``-i`` variants; use one
    # bounded alternative for a domain hypothesis, not a fuzzy web search.
    if "y" in brand:
        variants.append(brand.replace("y", "i"))
    return list(dict.fromkeys(f"https://{value}.{zone}" for value in variants for zone in ("ru", "com")))[:4]


def _default_search(query: str) -> tuple[list[str], list[str]]:
    return enrichment._domains_from_search(query)


def candidate_from_search_result(request: WebsiteDiscoveryRequest, candidate_url: str, search_query: str, *,
                                 search_position: int | None = None, search_title: str | None = None,
                                 search_snippet: str | None = None, candidate_source: str | None = None,
                                 source_type: str = "search_result", initial_evidence: list[str] | None = None,
                                 registry_sources: list[str] | None = None) -> WebsiteCandidate:
    """Classify and score a result without opening its domain.

    This preserves all five Tavily results in the audit trail and lets the
    workflow choose only the top three eligible domains for verification.
    """
    if registry_sources and source_type == "search_result":
        source_type = "registry_reported_website"
    normalized = normalize_candidate_url(candidate_url)
    domain = urllib.parse.urlparse(normalized).netloc.lower()
    role, role_reason = _classify_domain_role(normalized, title=search_title, snippet=search_snippet)
    candidate = WebsiteCandidate(
        candidate_url=normalized, domain=domain, search_query=search_query,
        search_position=search_position, search_title=search_title, search_snippet=search_snippet,
        candidate_source=candidate_source, source_type=source_type, domain_role=role.value,
        role_reason=role_reason,
    )
    candidate.positive_evidence.extend(initial_evidence or [])
    candidate.registry_sources = list(dict.fromkeys(registry_sources or []))
    if role in HARD_REJECT_ROLES:
        candidate.hard_rejected = True
        if role in {DomainRole.THIRD_PARTY_COMPANY_CARD, DomainRole.MULTITENANT_STOREFRONT, DomainRole.MARKETPLACE_CARD}:
            # Any company identifiers later observed in this kind of URL
            # describe the profile, not the owner of the host domain.
            candidate.identity_evidence_scope = "TARGET_COMPANY_PROFILE"
        candidate.verification_status = "rejected"
        candidate.candidate_status = "rejected"
        candidate.analysis_status = "skipped"
        candidate.selection_status = "HARD_REJECTED"
        candidate.rejection_reason = f"роль домена {role.value}: {role_reason}"
        candidate.negative_evidence.append(candidate.rejection_reason)
    elif role == DomainRole.PROJECT_OR_EVENT:
        candidate.hard_rejected = True
        candidate.verification_status = "requires_review"
        candidate.candidate_status = "requires_review"
        candidate.selection_status = "HARD_REJECTED"
        candidate.negative_evidence.append("Страница проекта не может быть автоматически выбрана основным сайтом.")
    elif len(set(candidate.registry_sources)) >= 2:
        # Two independent, INN-confirmed registry snapshots pointing at the
        # same non-directory domain are sufficient provenance to preserve the
        # relationship even if the public site cannot be fetched today.
        candidate.verification_status = "confirmed_by_registry"
        candidate.candidate_status = "confirmed"
        candidate.positive_evidence.append("домен совпал в двух независимых реестровых источниках")
    else:
        candidate.verification_status = "not_started"
    rescore_candidate(request, candidate)
    if candidate.hard_rejected:
        # A rejected role is recorded for auditing, but must not receive a
        # competing rank from title/snippet/position heuristics.
        candidate.search_score = candidate.candidate_score = 0.0
        candidate.score_components = {}
    if not candidate.shortlist_eligible and not candidate.hard_rejected:
        candidate.verification_status = "not_checked"
        candidate.candidate_status = "candidate"
        candidate.selection_status = "BELOW_SHORTLIST_THRESHOLD"
        candidate.verification_score = 0.0
        candidate.candidate_score = candidate.search_score
    return candidate


def verify_candidate(request: WebsiteDiscoveryRequest, candidate: WebsiteCandidate, *,
                       fetcher: Callable[[str], str] = enrichment._fetch) -> WebsiteCandidate:
    """Verify an already merged candidate; never reconstruct or rescore it."""
    rescore_candidate(request, candidate)
    if not candidate.shortlist_eligible:
        candidate.verification_status = "rejected" if candidate.hard_rejected else "not_checked"
        candidate.selection_status = "HARD_REJECTED" if candidate.hard_rejected else "BELOW_SHORTLIST_THRESHOLD"
        candidate.verification_score = 0.0
        candidate.candidate_score = candidate.search_score
        candidate.analysis_status = "skipped"
        return candidate
    domain = candidate.domain
    search_score = candidate.search_score
    collected: list[tuple[str, str]] = []
    urls = [candidate.candidate_url]
    try:
        root_body = fetcher(candidate.candidate_url)
    except Exception as exc:
        detail = str(exc).replace("\n", " ")[:500]
        candidate.negative_evidence.append(f"{candidate.candidate_url}: {type(exc).__name__}{': ' + detail if detail else ''}")
        candidate.fetch_status = _fetch_status(detail)
        candidate.verification_status = "confirmed_by_registry" if len(candidate.registry_sources) >= 2 else "probable" if (candidate.registry_sources or candidate.brand_match or search_score >= 60) else "requires_review"
        candidate.selection_status = "PROBABLE_UNAVAILABLE" if candidate.verification_status == "probable" else "VERIFIED_REGISTRY" if candidate.verification_status == "confirmed_by_registry" else "REQUIRES_REVIEW"
        candidate.analysis_status = "skipped"; candidate.candidate_score = round(search_score, 2); candidate.candidate_status = _legacy_status(candidate)
        candidate.negative_evidence = _unique(candidate.negative_evidence + ["Главная страница недоступна; это не означает, что домен не найден."])
        return candidate
    if root_body:
        candidate.checked_pages.append(candidate.candidate_url); collected.append((candidate.candidate_url, _page_text(root_body)))
        if _is_career_page(root_body):
            candidate.domain_role = DomainRole.PROJECT_OR_EVENT.value
            candidate.hard_rejected = True
            candidate.verification_status = "rejected"
            candidate.candidate_status = "rejected"
            candidate.analysis_status = "skipped"
            candidate.selection_status = "HARD_REJECTED"
            candidate.rejection_reason = "страница подбора персонала/стажировок не является официальным сайтом компании"
            candidate.negative_evidence.append(candidate.rejection_reason)
            candidate.verification_score = 0.0
            candidate.candidate_score = candidate.search_score
            return candidate
        selection = select_relevant_links(root_body, candidate.candidate_url, limit=MAX_SUBPAGES)
        candidate.positive_evidence = _unique(candidate.positive_evidence + [f"Главная страница: выбрано {len(selection.selected)} реальных внутренних ссылок."])
        urls.extend(link.url for link in selection.selected)
    for url in urls[1:]:
        try:
            body = fetcher(url)
        except Exception as exc:
            candidate.negative_evidence.append(f"{url}: {type(exc).__name__}: {str(exc).replace(chr(10), ' ')[:300]}")
            continue
        if body:
            candidate.checked_pages.append(url); collected.append((url, _page_text(body)))
    joined = " ".join(text for _, text in collected)
    if not joined:
        candidate.fetch_status = "empty_response"; candidate.verification_status = "probable" if candidate.registry_sources or candidate.brand_match or search_score >= 60 else "requires_review"
        candidate.selection_status = "PROBABLE_UNAVAILABLE" if candidate.verification_status == "probable" else "REQUIRES_REVIEW"
        candidate.analysis_status = "skipped"; candidate.candidate_score = round(search_score, 2); candidate.candidate_status = _legacy_status(candidate)
        return candidate
    candidate.fetch_status = "success"
    if _page_is_directory(domain, joined):
        candidate.domain_role = DomainRole.REGISTRY_DIRECTORY.value; candidate.hard_rejected = True; candidate.verification_status = "rejected"; candidate.analysis_status = "skipped"; candidate.candidate_status = "rejected"
        candidate.selection_status = "HARD_REJECTED"
        candidate.rejection_reason = "содержимое страницы является каталогом/реестром, а не сайтом компании"; candidate.negative_evidence.append(candidate.rejection_reason)
        candidate.verification_score = 0.0; candidate.candidate_score = candidate.search_score
        return candidate
    found_inns = _all_valid_inns(joined)
    # A candidate is an owner only on an allowed official domain.  The same
    # exact INN on Cibum/Focus is a target profile mention, never ownership.
    candidate.identity_evidence_scope = "WEBSITE_OWNER" if candidate.brand_match else "UNKNOWN"
    if not candidate.brand_match and candidate.domain_role != DomainRole.OFFICIAL_CANDIDATE.value:
        candidate.identity_evidence_scope = "TARGET_COMPANY_PROFILE" if request.inn in found_inns else "THIRD_PARTY_MENTION"
    if request.inn and request.inn not in found_inns and any(found != request.inn for found in found_inns) and not candidate.brand_match:
        candidate.verification_status = "rejected"; candidate.analysis_status = "skipped"; candidate.candidate_status = "rejected"
        candidate.selection_status = "HARD_REJECTED"
        candidate.rejection_reason = f"найден другой валидный ИНН: {sorted(found_inns - {request.inn})}"; candidate.negative_evidence.append(candidate.rejection_reason)
        return candidate
    if request.inn and request.inn not in found_inns and found_inns and candidate.brand_match:
        candidate.negative_evidence.append(f"домен бренда содержит другой ИНН {sorted(found_inns)}; требуется сверка входных реквизитов")
    identity = 0.0
    owner_evidence = candidate.identity_evidence_scope == "WEBSITE_OWNER" or candidate.brand_match
    if owner_evidence and request.inn and request.inn in found_inns:
        identity += 50; candidate.matched_inn = request.inn; candidate.positive_evidence.append(f"точный ИНН {request.inn} на домене (+50)")
    if owner_evidence and request.ogrn and re.sub(r"\D", "", request.ogrn) in re.sub(r"\D", "", joined):
        identity += 40; candidate.positive_evidence.append("найден ОГРН (+40)")
    if owner_evidence and _compatible_name(joined, request.confirmed_legal_name):
        identity += 30; candidate.matched_legal_name = True; candidate.positive_evidence.append("найдено совместимое юридическое наименование (+30)")
    if owner_evidence and request.kpp and re.sub(r"\D", "", request.kpp) in re.sub(r"\D", "", joined):
        candidate.matched_kpp = True; identity += 10; candidate.positive_evidence.append("совпал КПП (+10)")
    if owner_evidence and request.legal_address and clean_text(request.legal_address).lower() in clean_text(joined).lower():
        candidate.matched_address = True; identity += 10; candidate.positive_evidence.append("совпал юридический адрес (+10)")
    candidate.verification_score = round(identity, 2)
    candidate.candidate_score = round(search_score + identity, 2)
    if candidate.matched_inn or (owner_evidence and request.ogrn and re.sub(r"\D", "", request.ogrn) in re.sub(r"\D", "", joined)) or (candidate.matched_legal_name and search_score >= 65 and identity >= 30):
        candidate.verification_status = "confirmed_by_website"; candidate.selection_status = "VERIFIED"
    elif len(candidate.registry_sources) >= 2:
        candidate.verification_status = "confirmed_by_registry"; candidate.selection_status = "VERIFIED_REGISTRY"
    elif candidate.registry_sources or candidate.brand_match or search_score >= 40:
        candidate.verification_status = "probable"; candidate.selection_status = "PROBABLE"
    else:
        candidate.verification_status = "requires_review"; candidate.selection_status = "REQUIRES_REVIEW"
    candidate.candidate_status = _legacy_status(candidate)
    if candidate.verification_status in {"probable", "requires_review"}:
        candidate.negative_evidence.append("Поисковое совпадение не является юридическим подтверждением домена.")
    candidate.checked_pages = _unique(candidate.checked_pages)
    candidate.positive_evidence = _unique(candidate.positive_evidence)
    candidate.negative_evidence = _unique(candidate.negative_evidence)
    return candidate


def evaluate_candidate(request: WebsiteDiscoveryRequest, candidate_url: str, search_query: str, *,
                       search_position: int | None = None, search_title: str | None = None,
                       search_snippet: str | None = None, candidate_source: str | None = None,
                       source_type: str = "search_result", initial_evidence: list[str] | None = None,
                       registry_sources: list[str] | None = None,
                       fetcher: Callable[[str], str] = enrichment._fetch) -> WebsiteCandidate:
    candidate = candidate_from_search_result(
        request, candidate_url, search_query, search_position=search_position,
        search_title=search_title, search_snippet=search_snippet,
        candidate_source=candidate_source, source_type=source_type,
        initial_evidence=initial_evidence,
        registry_sources=registry_sources or ([candidate_source] if source_type == "registry_evidence" and candidate_source else []),
    )
    return verify_candidate(request, candidate, fetcher=fetcher)


def select_official_candidate(candidates: list[WebsiteCandidate]) -> WebsiteCandidate | None:
    """Choose one eligible company domain without reordering the raw report."""
    eligible = [item for item in candidates if _candidate_is_viable(item)]
    if not eligible:
        return None
    rank = {"confirmed_by_website": 4, "confirmed_by_registry": 3, "probable": 2, "requires_review": 1}
    return max(eligible, key=lambda item: (rank.get(item.verification_status, 0),
                                            int(bool(item.registry_sources)), len(set(item.registry_sources)),
                                            item.verification_score, item.search_score,
                                            -(item.search_position or 99)))


def discover_websites(request: WebsiteDiscoveryRequest, *, online: bool = False,
                      searcher: Callable[[str], tuple[list[str], list[str]]] = _default_search,
                      fetcher: Callable[[str], str] = enrichment._fetch) -> tuple[list[WebsiteCandidate], list[str]]:
    """Search two brand queries in order and preserve their raw candidate order."""
    if not online:
        return [], ["внешний поиск официального сайта технически заблокирован: нужен --confirm-external-run"]
    seen: set[str] = set(); candidates: list[WebsiteCandidate] = []; warnings: list[str] = []
    for query in build_queries(request):
        urls, diagnostics = searcher(query); warnings.extend(diagnostics)
        for position, url in enumerate(urls, 1):
            domain = urllib.parse.urlparse(normalize_candidate_url(url)).netloc.lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            candidates.append(evaluate_candidate(request, url, query, search_position=position, candidate_source="simple_search", source_type="search_result", fetcher=fetcher))
            if len(candidates) >= 5:
                return candidates, warnings
    return candidates, warnings
