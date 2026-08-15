"""Glue between the website services and the shared research store."""
from __future__ import annotations
import re
import urllib.parse
from pathlib import Path
from .website_analyzer import crawl_confirmed_site, save_analysis
from .website_discovery import (DomainRole, WebsiteCandidate, WebsiteDiscoveryRequest,
                                candidate_from_search_result, discover_websites, evaluate_candidate, normalize_candidate_url,
                                select_official_candidate, brand_domain_hypotheses, is_eligible_for_verification,
                                rescore_candidate, verify_candidate, registrable_domain)
from .tavily_search import TavilySearchProvider, build_tavily_queries, should_use_tavily_fallback

SITE_LABEL = re.compile(r"(?:официальн(?:ый|ого)?\s+сайт|сайт\s+компании|веб[-\s]?сайт|website|\bweb\b|\burl\b)", re.I)


def _registry_site_urls(html: str) -> list[tuple[str, str]]:
    """Extract only externally linked URLs that follow an explicit site label."""
    urls: list[tuple[str, str]] = []
    plain = re.sub(r"<[^>]+>", " ", html)
    # Find the position in the original HTML via the labelled tag.  This is
    # deliberately not one giant HTML regex: nested ``div`` blocks otherwise
    # make a prior container swallow the relevant <strong> label.
    for match in re.finditer(r"<(?:strong|b|span|div|dt)[^>]*>(?P<label>[^<]{0,120})</(?:strong|b|span|div|dt)>", html, re.I):
        label = re.sub(r"\s+", " ", match.group("label")).strip()
        if not SITE_LABEL.search(label):
            continue
        tail = html[match.end():match.end() + 800]
        link = re.search(r"<a[^>]+href=[\"'](?P<url>https?://[^\"'\s<>]+)[\"']", tail, re.I)
        if link:
            urls.append((link.group("url"), label))
    return list(dict.fromkeys(urls))


def registry_candidates_from_store(store, request: WebsiteDiscoveryRequest) -> tuple[list[WebsiteCandidate], list[dict]]:
    """Use saved registry pages before reaching any search engine."""
    rows = store.connection.execute(
        """SELECT source_name, source_url, request_status, snapshot_path, inn_confirmed FROM source_results
           WHERE company_id=? ORDER BY collected_at DESC""", (request.company_id,)
    ).fetchall()
    candidates_by_domain: dict[str, WebsiteCandidate] = {}
    diagnostics: list[dict] = []
    seen_sources, seen_urls = set(), set()
    for row in rows:
        source = row["source_name"]
        if source in seen_sources:
            continue
        seen_sources.add(source)
        detail = {"source": source, "status": "site_field_not_found", "source_url": row["source_url"], "site_url": None, "reason": "В сохранённой странице нет поля «Сайт»/«Веб-сайт» с внешней ссылкой."}
        path = row["snapshot_path"]
        if not path:
            detail.update(status="snapshot_unavailable", reason=f"Нет локального HTML snapshot; статус источника: {row['request_status']}.")
            diagnostics.append(detail); continue
        try:
            html = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            detail.update(status="snapshot_unavailable", reason=f"Snapshot недоступен: {type(exc).__name__}.")
            diagnostics.append(detail); continue
        found = _registry_site_urls(html)
        if not found:
            diagnostics.append(detail); continue
        if not row["inn_confirmed"]:
            detail.update(status="unconfirmed_source", reason="Источник не подтвердил исходный ИНН; ссылка не принята как кандидат.")
            diagnostics.append(detail); continue
        detail.update(status="candidate", site_url=found[0][0], reason=f"Найдена явно обозначенная ссылка: {found[0][1]}.")
        diagnostics.append(detail)
        for url, label in found:
            domain = urllib.parse.urlparse(url).netloc.lower()
            if not domain:
                continue
            if domain in candidates_by_domain:
                existing = candidates_by_domain[domain]
                existing.registry_sources.append(source)
                existing.positive_evidence.append(f"{source}: поле «{label}» содержит URL {url}")
                continue
            seen_urls.add(domain)
            candidates_by_domain[domain] = WebsiteCandidate(candidate_url=url, domain=domain, search_query=f"registry:{source}", candidate_source=source,
                                                            source_type="registry_reported_website",
                                                            positive_evidence=[f"{source}: поле «{label}» содержит URL {url}"],
                                                            registry_sources=[source], checked_pages=[])
    return list(candidates_by_domain.values()), diagnostics

def discovery_request_from_store(store, company_id: int) -> WebsiteDiscoveryRequest:
    company = store.connection.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    aliases = [row[0] for row in store.connection.execute(
        "SELECT original_name FROM company_aliases WHERE company_id=? ORDER BY id", (company_id,)
    ).fetchall()]
    facts = {row["field_name"]: row["value_text"] for row in store.connection.execute("SELECT field_name, value_text FROM company_facts WHERE company_id=? AND is_conflicting=0", (company_id,)).fetchall()}
    primary = store.connection.execute("SELECT okved_code FROM company_okved WHERE company_id=? AND is_primary=1 AND is_conflicting=0 LIMIT 1", (company_id,)).fetchone()
    additional = [row[0] for row in store.connection.execute("SELECT DISTINCT okved_code FROM company_okved WHERE company_id=? AND is_primary=0", (company_id,)).fetchall()]
    return WebsiteDiscoveryRequest(company_id, company["inn"], company["kpp"] or facts.get("kpp"), company["confirmed_legal_name"] or facts.get("legal_name"), aliases,
                                   company["ogrn"] or facts.get("ogrn"), company["legal_address"] or facts.get("address"), company["region"] or facts.get("region"),
                                   primary[0] if primary else None, additional)

def _save_attempt(store, company_id: int, payload: dict) -> None:
    """Best-effort audit recording; discovery must continue if audit storage fails."""
    try:
        store.record_website_search_attempt(company_id, payload)
    except Exception:
        pass


def _merge_candidate(existing: WebsiteCandidate, incoming: WebsiteCandidate) -> WebsiteCandidate:
    """Merge provenance for a repeated domain without hiding Tavily rank."""
    existing.registry_sources = list(dict.fromkeys(existing.registry_sources + incoming.registry_sources))
    for value in incoming.positive_evidence:
        if value not in existing.positive_evidence:
            existing.positive_evidence.append(value)
    # Keep the best ranked search presentation while retaining registry
    # provenance.  Score calculation is intentionally deferred until all
    # sources for the registrable domain have been merged.
    if incoming.search_position is not None and (existing.search_position is None or incoming.search_position < existing.search_position):
        existing.search_query = incoming.search_query
        existing.search_position = incoming.search_position
        existing.search_title = incoming.search_title
        existing.search_snippet = incoming.search_snippet
    if existing.registry_sources:
        existing.candidate_source = "tavily+registry" if incoming.source_type == "tavily_search" or existing.candidate_source == "tavily" else "+".join(existing.registry_sources)
        existing.source_type = "registry_reported_website"
    elif incoming.source_type == "tavily_search":
        existing.candidate_source = "tavily"
        existing.source_type = "tavily_search"
    existing.negative_evidence = list(dict.fromkeys(existing.negative_evidence + incoming.negative_evidence))
    existing.checked_pages = list(dict.fromkeys(existing.checked_pages + incoming.checked_pages))
    return existing


def discover_and_store(store, company_id: int, *, online: bool = False, searcher=None, fetcher=None,
                       diagnostics: list[dict] | None = None, tavily_provider: TavilySearchProvider | None = None,
                       max_tavily_credits: int | None = None):
    """Discover, rank and verify official-site candidates deterministically.

    Registry URLs and all five Tavily results are retained.  Domain-role
    filtering happens before fetches; then only the three best eligible
    candidates are opened on their own domain for legal-identity checks.
    """
    request = discovery_request_from_store(store, company_id)
    registry, registry_diagnostics = registry_candidates_from_store(store, request)
    if diagnostics is not None:
        diagnostics.extend(registry_diagnostics)
    _save_attempt(store, company_id, {"provider": "registry", "reason_for_call": "registry_site_urls",
                                      "status": "candidates_found" if registry else "no_results", "result_count": len(registry)})
    candidates_by_domain: dict[str, WebsiteCandidate] = {}
    raw_order: list[str] = []
    def add(candidate: WebsiteCandidate) -> None:
        key = registrable_domain(candidate.domain or candidate.candidate_url)
        if not key:
            return
        if key in candidates_by_domain:
            _merge_candidate(candidates_by_domain[key], candidate)
        else:
            candidates_by_domain[key] = candidate
            raw_order.append(key)

    for registry_candidate in registry:
        add(candidate_from_search_result(
            request, registry_candidate.candidate_url, registry_candidate.search_query,
            candidate_source=registry_candidate.candidate_source, source_type="registry_reported_website",
            initial_evidence=registry_candidate.positive_evidence,
            registry_sources=registry_candidate.registry_sources,
        ))

    warnings: list[str] = []
    if online and tavily_provider is None and searcher is not None:
        # Test-only compatibility for deterministic local fixtures.  The
        # production runner provides a Tavily provider and never reaches it.
        kwargs = {"online": True, "searcher": searcher}
        if fetcher is not None:
            kwargs["fetcher"] = fetcher
        searched, warnings = discover_websites(request, **kwargs)
        if registry:
            warnings.insert(0, "registry candidates were rejected or unverified; fallback brand search executed")
        for candidate in searched:
            add(candidate)
    elif online:
        provider = tavily_provider or TavilySearchProvider()
        if max_tavily_credits is not None:
            provider.config = provider.config.__class__(**{**provider.config.__dict__, "max_credits_per_run": max(1, max_tavily_credits)})
        preflight = provider.preflight()
        _save_attempt(store, company_id, preflight.public_dict())
        if preflight.status == "ready":
            queries = build_tavily_queries(request, "BRAND_TOP5", max_calls=1)
            for query in queries:
                attempt, results = provider.search(query, "BRAND_TOP5")
                for result in results[:5]:
                    candidate = candidate_from_search_result(
                        request, result.url, result.search_query, search_position=result.rank,
                        search_title=result.title, search_snippet=result.content, candidate_source="tavily",
                        source_type="tavily_search",
                        initial_evidence=[f"Tavily Search: шаблон {result.query_template_id}; rank={result.rank}; request_id={result.request_id or 'нет'}"],
                    )
                    add(candidate)
                    if candidate.verification_status == "rejected":
                        attempt.rejected_count += 1
                    else:
                        attempt.accepted_count += 1
                _save_attempt(store, company_id, attempt.__dict__)
        elif diagnostics is not None:
            diagnostics.append({"source": "Tavily", "status": preflight.status, "site_url": None,
                                "reason": preflight.error_message or preflight.status})

    candidates = [candidates_by_domain[key] for key in raw_order]
    # The score is computed once, after Tavily/simple/registry provenance was
    # merged.  A hard-rejected card is never fetched even when it contains the
    # target INN in its own profile.
    for item in candidates:
        rescore_candidate(request, item)
        if item.hard_rejected:
            item.shortlist_eligible = False
            item.verification_score = 0.0
            item.candidate_score = item.search_score
            item.selection_status = "HARD_REJECTED"
        elif not is_eligible_for_verification(item):
            item.shortlist_eligible = False
            item.verification_status = "not_checked"
            item.verification_score = 0.0
            item.candidate_score = item.search_score
            item.selection_status = "BELOW_SHORTLIST_THRESHOLD"
        else:
            item.shortlist_eligible = True
    eligible = [item for item in candidates if item.shortlist_eligible and item.verification_status in {"not_started", "confirmed_by_registry"}
                and item.domain_role == DomainRole.OFFICIAL_CANDIDATE.value]
    # An explicitly labelled website from an INN-confirmed registry is more
    # trustworthy than a visually similar search result.  Verify it first so
    # a careers microsite cannot consume the three verification slots.
    eligible.sort(key=lambda item: (-int(bool(item.registry_sources)), -len(set(item.registry_sources)),
                                   -item.search_score, item.search_position or 99, item.domain))
    for pending in eligible[:3]:
        verified = verify_candidate(request, pending, **({"fetcher": fetcher} if fetcher is not None else {}))
        index = candidates.index(pending)
        candidates[index] = verified

    for candidate in candidates:
        candidate.selected = False
    selected = select_official_candidate(candidates)
    if selected:
        selected.selected = True
        selected.selection_status = selected.selection_status if selected.selection_status not in {"NOT_CHECKED", "BELOW_SHORTLIST_THRESHOLD"} else "SELECTED"
    if online:
        for candidate in candidates:
            store.add_website_candidate(company_id, candidate_url=candidate.candidate_url, search_query=candidate.search_query,
                candidate_source=candidate.candidate_source,
                search_position=candidate.search_position, search_title=candidate.search_title, search_snippet=candidate.search_snippet,
                score=candidate.candidate_score, status=candidate.candidate_status, positive_evidence=candidate.positive_evidence,
                negative_evidence=candidate.negative_evidence, checked_pages=candidate.checked_pages,
                discovery_status=candidate.discovery_status, verification_status=candidate.verification_status,
                fetch_status=candidate.fetch_status, analysis_status=candidate.analysis_status,
                registry_sources=candidate.registry_sources, source_type=candidate.source_type,
                domain_role=candidate.domain_role, brand_match=candidate.brand_match, title_match=candidate.title_match,
                rejection_reason=candidate.rejection_reason, role_reason=candidate.role_reason,
                search_score=candidate.search_score, verification_score=candidate.verification_score,
                selected=candidate.selected, hard_rejected=candidate.hard_rejected,
                shortlist_eligible=candidate.shortlist_eligible, selection_status=candidate.selection_status,
                score_components=candidate.score_components, identity_evidence_scope=candidate.identity_evidence_scope)
        # Only one selected official/probable candidate may enter the analysis
        # queue.  Registry directories and rejected links cannot reach it.
        if selected and selected.verification_status in {"confirmed_by_website", "confirmed_by_registry", "probable"}:
            store.add_website(company_id, selected.candidate_url, selected.verification_status, selected.candidate_score,
                              "website_discovery", discovery_status=selected.discovery_status,
                              fetch_status=selected.fetch_status, analysis_status=selected.analysis_status)
        store.connection.commit()
    return candidates, warnings

def analyze_confirmed_and_store(store, company_id: int, *, online: bool = False, fetcher=None):
    website = store.analysis_website(company_id)
    if not website:
        return None, ["анализ не запущен: нет подтверждённого сайта либо доступного probable-кандидата"]
    if not online:
        return None, ["внешняя загрузка страниц технически заблокирована: нужен --confirm-external-run"]
    result = crawl_confirmed_site(website["website_url"], **({"fetcher": fetcher} if fetcher else {}))
    company = store.connection.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    save_analysis(store, company_id, website["id"], company["inn"], website["domain"] or "site", result, company["confirmed_legal_name"])
    store.update_website_analysis_status(website["id"], result.status)
    store.update_candidate_analysis_status(company_id, website["website_url"], result.status)
    store.connection.commit()
    return result, []
