"""Official-site discovery after a legal entity has been identified by INN."""
from __future__ import annotations

import html
import base64
import gzip
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from collections import OrderedDict
from collections.abc import Callable
from .schemas import WebsiteResult

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
LEGAL_PATHS = ("/", "/contacts", "/contact", "/requisites", "/rekvizity", "/about", "/offer", "/privacy", "/politika-konfidentsialnosti")


class HtmlFetchBlockedError(RuntimeError):
    """The server returned an anti-bot/WAF interstitial, not usable HTML."""


@dataclass
class HtmlFetchResult:
    requested_url: str
    final_url: str | None = None
    status: int | None = None
    redirects: list[str] = field(default_factory=list)
    content_type: str | None = None
    content_encoding: str | None = None
    size: int = 0
    body: str = ""
    error: str | None = None
    blocked_by_waf: bool = False


class _TrackingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirects: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.redirects.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url: str, timeout: float = 12) -> HtmlFetchResult:
    """Load one public HTML page with browser-like but non-invasive headers.

    Standard-library urllib is retained; TLS certificate verification stays on.
    Brotli is deliberately not requested because urllib has no built-in decoder.
    """
    redirects = _TrackingRedirectHandler()
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip",
    })
    result = HtmlFetchResult(requested_url=url, redirects=redirects.redirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(750_000)
            result.final_url, result.status = response.geturl(), response.status
            result.content_type = response.headers.get("Content-Type")
            result.content_encoding = response.headers.get("Content-Encoding")
            if (result.content_encoding or "").lower() == "gzip":
                raw = gzip.decompress(raw)
            result.size = len(raw)
            charset = response.headers.get_content_charset() or "utf-8"
            result.body = raw.decode(charset, errors="replace")
            probe = result.body.lower()
            result.blocked_by_waf = any(marker in probe for marker in ("user_blocked", "bobcmn", "tspd", "akamai", "access denied"))
            if result.blocked_by_waf:
                result.error = "blocked_by_waf: сервер вернул anti-bot interstitial вместо содержательной HTML-страницы"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def _fetch(url: str, timeout: float = 12) -> str:
    result = fetch_html(url, timeout)
    if result.error:
        raise HtmlFetchBlockedError(
            f"{result.error}; status={result.status}; final_url={result.final_url}; size={result.size}; content_type={result.content_type}"
        )
    return result.body


def _text(raw_html: str) -> str:
    stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", stripped))).upper()


def _normal_tokens(value: str) -> set[str]:
    ignored = {"ООО", "АО", "ПАО", "ЗАО", "НАО", "ИП", "БАНК", "КОМПАНИЯ"}
    return {x for x in re.findall(r"[A-ZА-ЯЁ0-9]{3,}", value.upper().replace("Ё", "Е")) if x not in ignored}


def _domains_from_html(page: str, query: str | None = None) -> list[str]:
    links = re.findall(r'<a\b[^>]*\bhref=["\'](.*?)["\'][^>]*>(.*?)</a>', page, flags=re.I | re.S)
    ignored_terms = {"официальный", "сайт", "инн", "реквизиты"}
    query_terms = {term for term in re.findall(r"[а-яёa-z]{4,}", (query or "").lower()) if term not in ignored_terms}
    domains: OrderedDict[str, None] = OrderedDict()
    for link, label in links:
        target = html.unescape(link)
        parsed = urllib.parse.urlparse(target)
        query = urllib.parse.parse_qs(parsed.query)
        # DuckDuckGo wraps results in ``uddg`` even when the wrapper has a
        # netloc. Bing's ``u=a1<base64-url>`` is likewise a public result link.
        if query.get("uddg"):
            target = query["uddg"][0]
            parsed = urllib.parse.urlparse(target)
        elif "bing.com" in parsed.netloc and query.get("u"):
            encoded = query["u"][0]
            if encoded.startswith("a1"):
                try:
                    target = base64.b64decode(encoded[2:] + "===").decode("utf-8", errors="ignore")
                    parsed = urllib.parse.urlparse(target)
                except Exception:
                    pass
        candidate_text = (re.sub(r"<[^>]+>", " ", html.unescape(label)) + " " + parsed.netloc).lower().replace("ё", "е")
        normalized_terms = {term.replace("ё", "е") for term in query_terms}
        if normalized_terms and not any(term in candidate_text for term in normalized_terms):
            continue
        if parsed.scheme in {"http", "https"} and parsed.netloc and "duckduckgo" not in parsed.netloc and "bing.com" not in parsed.netloc:
            domains[f"{parsed.scheme}://{parsed.netloc}"] = None
    return list(domains)[:5]


def _domains_from_search(query: str) -> tuple[list[str], list[str]]:
    encoded = urllib.parse.quote(query)
    failures: list[str] = []
    for provider, url in (
        ("DuckDuckGo", "https://html.duckduckgo.com/html/?q=" + encoded),
        ("Bing", "https://www.bing.com/search?q=" + encoded),
    ):
        try:
            domains = _domains_from_html(_fetch(url), query)
        except Exception as exc:
            failures.append(f"{provider}: {type(exc).__name__}")
            continue
        if domains:
            return domains, failures
        failures.append(f"{provider}: кандидаты не найдены")
    return [], failures


def discover_official_site(
    legal_name: str,
    inn: str | None,
    *,
    online: bool = True,
    searcher: Callable[[str], tuple[list[str], list[str]]] = _domains_from_search,
    fetcher: Callable[[str], str] = _fetch,
) -> WebsiteResult:
    """Find a domain by legal name, then prove the domain belongs to that entity.

    Search result ranking is never evidence. A domain is confirmed only with
    score >= 0.80: INN + legal-name/legal-page evidence. Scores 0.60–0.79 are
    stored as candidates but are not returned as the official URL.
    """
    if not online:
        return WebsiteResult(status="not_run", evidence=["веб-поиск отключён"])
    # Legacy helper remains available for callers outside the shared website
    # workflow.  Keep its discovery human-like: identifiers are verification
    # data, never public search terms.
    queries = [legal_name, f"{legal_name} официальный сайт"]
    candidates: OrderedDict[str, None] = OrderedDict()
    diagnostics: list[str] = []
    for query in queries:
        domains, messages = searcher(query)
        diagnostics.extend(messages)
        for domain in domains:
            candidates[domain] = None
    if not candidates:
        return WebsiteResult(status="not_found", search_queries=queries, evidence=["сайт не найден: поисковые источники не вернули кандидатов", *diagnostics])

    legal_tokens = _normal_tokens(legal_name)
    best = WebsiteResult(status="not_found", search_queries=queries, checked_candidates=list(candidates))
    for domain in candidates:
        pages: list[str] = []
        page_text = ""
        for path in LEGAL_PATHS:
            url = urllib.parse.urljoin(domain, path)
            try:
                text = _text(fetcher(url))
                if text:
                    page_text += " " + text
                    pages.append(url)
            except Exception:
                continue
        if not page_text:
            continue
        score, evidence = 0.0, []
        if inn and inn in re.sub(r"\D", "", page_text):
            score += .60
            evidence.append(f"ИНН {inn} найден на странице {pages[0]}")
        page_tokens = _normal_tokens(page_text)
        overlap = len(legal_tokens & page_tokens) / max(1, len(legal_tokens))
        if overlap >= .70:
            score += .20
            evidence.append("на сайте найдено юридическое наименование")
        legal_page_present = any(any(marker in url.lower() for marker in ("contact", "requisite", "rekviz", "offer", "privacy")) for url in pages)
        if legal_page_present:
            score += .10
            evidence.append("проверена юридическая или контактная страница")
        status = "confirmed" if score >= .80 else "candidate" if score >= .60 else "rejected"
        result = WebsiteResult(url=domain if status == "confirmed" else None, candidate_url=domain, score=round(score, 2), status=status,
                               search_queries=queries, checked_candidates=list(candidates), evidence=evidence, conflicts=[])
        if result.score > best.score:
            best = result
    if best.score == 0:
        best.evidence = ["сайт не найден: кандидаты не содержат проверяемых реквизитов", *diagnostics]
    elif best.status == "candidate":
        best.evidence.append("кандидат не принят: недостаточно двух независимых подтверждений")
    return best


def verify_official_site(inn: str | None, company_name: str, *, online: bool = True) -> WebsiteResult:
    """Compatibility wrapper for the classifier; the query is now name-first."""
    return discover_official_site(company_name, inn, online=online)
