"""Safe, auditable Tavily fallback for official-site discovery.

The provider deliberately knows only public company identity data.  It never
receives payment operations, model features, scores, or a predicted class.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .normalization import clean_text

SEARCH_ENDPOINT = "https://api.tavily.com/search"
USAGE_ENDPOINT = "https://api.tavily.com/usage"
MAP_ENDPOINT = "https://api.tavily.com/map"
EXTRACT_ENDPOINT = "https://api.tavily.com/extract"
DEFAULT_EXCLUDE_DOMAINS = [
    "checko.ru", "zachestnyibiznes.ru", "rusprofile.ru", "companies.rbc.ru",
    "sbis.ru", "list-org.com", "audit-it.ru", "focus.kontur.ru", "kontur.ru", "kontur.tech", "kontur-fokus.ru", "spark-interfax.ru",
    "kontragent.vbr.ru", "e-disclosure.ru", "finmarket.ru", "raexpert.ru", "ra-national.ru",
    "rkn.gov.ru", "xfirm.ru", "b2b-center.ru", "banki.ru", "2gis.ru",
    "vk.com", "t.me", "telegram.org", "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "wikipedia.org",
]
FETCH_LAYER_STATUSES = {
    "timeout", "connection_error", "blocked_by_waf", "blocked_by_access_control",
    "http_401", "http_403", "http_404", "http_498", "empty_response", "error",
    "invalid_content_type", "redirect_loop",
}


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _load_local_env() -> None:
    """Load project-local .env for standalone scripts without a dependency."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def redact_secret(value: str | None, secret: str | None = None) -> str:
    """Remove an API key from text before it can enter evidence or logs."""
    result = str(value or "")
    if secret:
        result = result.replace(secret, "***REDACTED***")
    return re.sub(r"tvly-[A-Za-z0-9_-]+", "***REDACTED***", result)


def _safe_text(value: str | None, limit: int = 400) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    return text[:limit]


def _query_value(value: str | None, limit: int) -> str:
    """Sanitise a query substitution without leaving nested quote syntax."""
    return _safe_text(value, limit).replace('"', "").replace("'", "").strip()


@dataclass(frozen=True)
class TavilyConfig:
    enabled: bool
    api_key: str | None
    project_id: str
    max_results: int
    timeout_seconds: int
    connect_timeout_seconds: int
    max_retries: int
    max_calls_per_company: int
    max_credits_per_run: int
    monthly_soft_limit: int
    allow_paid: bool
    require_usage_preflight: bool
    search_depth: str = "basic"
    country: str | None = "russia"

    @classmethod
    def from_env(cls) -> "TavilyConfig":
        _load_local_env()
        search_depth = _safe_text(os.getenv("TAVILY_SEARCH_DEPTH", "basic"), 20).lower()
        # Keep the automatic path on one-credit modes.  Advanced Search costs
        # two credits and is intentionally not enabled by environment typo.
        if search_depth not in {"basic", "fast", "ultra-fast"}:
            search_depth = "basic"
        country = _safe_text(os.getenv("TAVILY_COUNTRY", "russia"), 80).lower() or None
        return cls(
            enabled=_flag("TAVILY_ENABLED"),
            api_key=os.getenv("TAVILY_API_KEY") or None,
            # Project tracking is optional.  Sending an arbitrary project ID
            # scopes /usage to a project the key may not own and Tavily then
            # returns an empty object, which must not look like zero quota.
            project_id=_safe_text(os.getenv("TAVILY_PROJECT_ID") or os.getenv("TAVILY_PROJECT") or "", 120),
            max_results=max(1, min(_int("TAVILY_MAX_RESULTS", 5), 10)),
            timeout_seconds=max(1, min(_int("TAVILY_TIMEOUT_SECONDS", 30), 60)),
            connect_timeout_seconds=max(1, min(_int("TAVILY_CONNECT_TIMEOUT_SECONDS", 10), 30)),
            max_retries=max(0, min(_int("TAVILY_MAX_RETRIES", 2), 2)),
            max_calls_per_company=max(1, min(_int("TAVILY_MAX_CALLS_PER_COMPANY", 2), 2)),
            max_credits_per_run=max(1, _int("TAVILY_MAX_CREDITS_PER_RUN", 50)),
            monthly_soft_limit=max(1, _int("TAVILY_MONTHLY_SOFT_LIMIT", 900)),
            allow_paid=False,  # Paid operation is intentionally impossible in this project.
            require_usage_preflight=_flag("TAVILY_REQUIRE_USAGE_PREFLIGHT", True),
            search_depth=search_depth,
            country=country,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "api_key_configured": bool(self.api_key),
            "project_id": self.project_id, "max_results": self.max_results,
            "timeout_seconds": self.timeout_seconds, "connect_timeout_seconds": self.connect_timeout_seconds,
            "max_retries": self.max_retries, "max_calls_per_company": self.max_calls_per_company,
            "max_credits_per_run": self.max_credits_per_run, "monthly_soft_limit": self.monthly_soft_limit,
            "allow_paid": False, "require_usage_preflight": self.require_usage_preflight,
            "search_depth": self.search_depth, "country": self.country,
        }


@dataclass(frozen=True)
class TavilyQuery:
    template_id: str
    query: str
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_DOMAINS))


@dataclass
class TavilyAttempt:
    provider: str = "tavily"
    reason_for_call: str = ""
    template_id: str = ""
    query: str = ""
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    status: str = "not_started"
    http_status: int | None = None
    request_id: str | None = None
    response_time: float | None = None
    result_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    credits_used: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("raw_response", None)
        return value


@dataclass(frozen=True)
class TavilyResult:
    rank: int
    title: str
    url: str
    content: str
    score: float | None
    query_template_id: str
    search_query: str
    request_id: str | None
    response_time: float | None
    credits_used: int | None


def _error_message(payload: dict[str, Any] | None, fallback: str = "Tavily request failed") -> str:
    """Read Tavily's documented error envelope without leaking credentials."""
    if not isinstance(payload, dict):
        return fallback
    message = payload.get("message")
    if message:
        return str(message)
    detail = payload.get("detail")
    if isinstance(detail, dict) and detail.get("error"):
        return str(detail["error"])
    if isinstance(detail, str) and detail:
        return detail
    return fallback


def _brand(request: Any) -> str | None:
    # Keep the public search string identical to the discovery workflow.  The
    # import is local to avoid a module-level dependency cycle.
    from .website_discovery import _brand as discovery_brand
    return _safe_text(discovery_brand(request), 160) or None


def build_tavily_queries(request: Any, reason: str, *, candidate_domains: list[str] | None = None,
                         max_calls: int = 2) -> list[TavilyQuery]:
    """Create one brand discovery query; identity values are verification-only.

    ``INN``/``OGRN`` remain permitted for a future, explicitly scoped
    evidence-page lookup.  They are never part of public-domain discovery.
    """
    legal = _query_value(getattr(request, "confirmed_legal_name", None), 220)
    inn = _query_value(getattr(request, "inn", None), 20)
    ogrn = _query_value(getattr(request, "ogrn", None), 24)
    region = _query_value(getattr(request, "region", None), 100)
    brand = _query_value(_brand(request), 160)
    domains = [d.lower().strip() for d in (candidate_domains or []) if d]
    queries: list[TavilyQuery] = []
    if reason == "EVIDENCE_PAGE_LOOKUP" and domains:
        domain = domains[0]
        if inn:
            queries.append(TavilyQuery("DOMAIN_INN_EVIDENCE", f'"{inn}" реквизиты', [domain], []))
        if ogrn and len(queries) < max_calls:
            short = brand or legal
            queries.append(TavilyQuery("DOMAIN_OGRN_EVIDENCE", f'"{ogrn}" "{short}"', [domain], []))
        return queries[:max_calls]
    discovery_brand = brand or legal
    if discovery_brand:
        # Discovery is intentionally the bare public brand.  Legal identity
        # data belongs to the later verifier, not the search string.
        queries.append(TavilyQuery("BRAND_TOP5", discovery_brand))
    deduped: list[TavilyQuery] = []
    seen: set[str] = set()
    for item in queries:
        normalized = clean_text(item.query).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(TavilyQuery(item.template_id, item.query[:400], item.include_domains, item.exclude_domains))
    return deduped[:1]


def should_use_tavily_fallback(candidates: list[Any]) -> tuple[bool, str]:
    """Decide whether an unconfirmed discovery result needs an extra search.

    A loader failure is still recorded as a loader failure.  Tavily is not a
    WAF bypass, but one bounded identity query can find an alternative legal
    or requisites page when a registry URL cannot be verified locally.
    """
    if not candidates:
        return True, "NO_CANDIDATES"
    statuses = {getattr(item, "verification_status", "") for item in candidates}
    fetch_statuses = {getattr(item, "fetch_status", "") for item in candidates}
    if fetch_statuses & FETCH_LAYER_STATUSES and all(value in FETCH_LAYER_STATUSES | {"not_started"} for value in fetch_statuses):
        return True, "FETCH_FAILURE_ALTERNATIVE_DISCOVERY"
    if any(value.startswith("confirmed") for value in statuses):
        return False, "verified_site_already_exists"
    if any(getattr(item, "domain_role", "OFFICIAL_CANDIDATE") == "OFFICIAL_CANDIDATE" and
           getattr(item, "verification_status", "") in {"confirmed_by_website", "confirmed_by_registry", "probable"} and
           (getattr(item, "brand_match", False) or len(set(getattr(item, "registry_sources", []) or [])) >= 2)
           for item in candidates):
        return False, "viable_official_domain_already_exists"
    if statuses == {"rejected"}:
        if all("другой валидный ИНН" in " ".join(getattr(item, "negative_evidence", [])) for item in candidates):
            return True, "ALL_CANDIDATES_WRONG_COMPANY"
        return True, "ONLY_DIRECTORY_CANDIDATES"
    if any(value in {"probable", "requires_review"} for value in statuses):
        return True, "UNCONFIRMED_CANDIDATE_DISCOVERY"
    return True, "NO_VERIFIABLE_EVIDENCE"


class TavilySearchProvider:
    """Direct REST client with conservative free-credit guards and no SDK dependency."""

    def __init__(self, config: TavilyConfig | None = None,
                 request: Callable[..., Any] | None = None) -> None:
        self.config = config or TavilyConfig.from_env()
        self._request = request or urllib.request.urlopen
        self.run_credits_used = 0
        self.disabled_for_run = False
        self.usage: dict[str, Any] | None = None
        self._preflight_attempt: TavilyAttempt | None = None

    def is_available(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "tavily_disabled"
        if not self.config.api_key:
            return False, "api_key_missing"
        if self.config.allow_paid:
            return False, "paid_mode_forbidden"
        return True, "ready"

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        if self.config.project_id:
            headers["X-Project-ID"] = self.config.project_id
        return headers

    def _call_json(self, url: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], dict[str, str]]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, headers=self._headers(), method="POST" if data else "GET")
        try:
            with self._request(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read(1_000_000)
                raw_headers = getattr(response, "headers", None) or {}
                headers = {str(key).lower(): str(value) for key, value in raw_headers.items()}
                return int(getattr(response, "status", 200)), json.loads(raw.decode("utf-8")), headers
        except urllib.error.HTTPError as exc:
            raw = exc.read(100_000).decode("utf-8", errors="replace")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                response = {"message": raw[:1000]}
            raw_headers = getattr(exc, "headers", None) or {}
            headers = {str(key).lower(): str(value) for key, value in raw_headers.items()}
            return int(exc.code), response, headers

    def preflight(self) -> TavilyAttempt:
        if self._preflight_attempt is not None:
            return TavilyAttempt(**asdict(self._preflight_attempt))
        attempt = TavilyAttempt(status="not_started")
        available, reason = self.is_available()
        if not available:
            attempt.status = reason
            self._preflight_attempt = attempt
            return attempt
        if not self.config.require_usage_preflight:
            attempt.status = "ready"
            self._preflight_attempt = attempt
            return attempt
        try:
            status, payload, _headers = self._call_json(USAGE_ENDPOINT)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            attempt.status, attempt.error_type = "usage_check_failed", type(exc).__name__
            attempt.error_message = redact_secret(str(exc), self.config.api_key)
            self._preflight_attempt = attempt
            return attempt
        attempt.http_status = status
        if status != 200 or not isinstance(payload, dict):
            attempt.status = "usage_check_failed"
            attempt.error_message = redact_secret(_error_message(payload, str(status)), self.config.api_key)
            self._preflight_attempt = attempt
            return attempt
        self.usage = payload
        key, account = payload.get("key") or {}, payload.get("account") or {}
        usage, limit = key.get("usage"), key.get("limit")
        paygo = account.get("paygo_usage", 0) or 0
        if not isinstance(usage, (int, float)) or not isinstance(limit, (int, float)):
            attempt.status = "usage_check_failed"
            attempt.error_message = (
                "Tavily Usage API вернул ответ без key.usage/key.limit; "
                "проверьте TAVILY_PROJECT_ID или оставьте его пустым."
            )
        elif paygo or usage >= limit or usage >= self.config.monthly_soft_limit or limit - usage < 100:
            attempt.status = "free_quota_exhausted"
        else:
            attempt.status = "ready"
        self._preflight_attempt = attempt
        return attempt

    @staticmethod
    def _status_for_http(status: int) -> str:
        return {400: "invalid_request", 401: "invalid_api_key", 403: "forbidden", 429: "rate_limited",
                432: "quota_or_plan_limit", 433: "paygo_limit"}.get(status, "provider_error")

    @staticmethod
    def _retry_delay(headers: dict[str, str], retry_number: int) -> float:
        """Respect Tavily's Retry-After header, bounded to one minute."""
        try:
            retry_after = float(headers.get("retry-after", ""))
            if retry_after >= 0:
                return min(retry_after, 60.0)
        except (TypeError, ValueError):
            pass
        return min(0.5 * (2 ** retry_number), 60.0)

    def search(self, query: TavilyQuery, reason: str) -> tuple[TavilyAttempt, list[TavilyResult]]:
        attempt = TavilyAttempt(reason_for_call=reason, template_id=query.template_id, query=query.query,
                                include_domains=query.include_domains, exclude_domains=query.exclude_domains)
        if self.disabled_for_run:
            attempt.status = "free_quota_exhausted"
            return attempt, []
        available, availability = self.is_available()
        if not available:
            attempt.status = availability
            return attempt, []
        if self.run_credits_used >= self.config.max_credits_per_run:
            attempt.status = "run_credit_limit_reached"
            return attempt, []
        payload = {"query": query.query, "search_depth": self.config.search_depth,
                   # Discovery deliberately receives one bare-brand query and
                   # five raw candidates; selection is local and auditable.
                   "max_results": 5 if query.template_id == "BRAND_TOP5" else self.config.max_results,
                   "topic": "general", "include_answer": False, "include_raw_content": False,
                   "include_images": False, "include_image_descriptions": False, "include_favicon": False,
                   "include_domains": query.include_domains, "exclude_domains": query.exclude_domains,
                   "country": self.config.country, "auto_parameters": False, "exact_match": False, "include_usage": True,
                   "safe_search": False}
        for number in range(self.config.max_retries + 1):
            started = time.monotonic()
            try:
                status, response, headers = self._call_json(SEARCH_ENDPOINT, payload)
            except TimeoutError as exc:
                status, response, headers = 0, {"message": str(exc), "_network_error": "timeout"}, {}
            except (urllib.error.URLError, OSError) as exc:
                status, response, headers = 0, {"message": str(exc), "_network_error": "connection_error"}, {}
            attempt.response_time = round(time.monotonic() - started, 3)
            attempt.http_status = status or None
            if status == 200:
                if not isinstance(response, dict) or not isinstance(response.get("results"), list):
                    attempt.status = "invalid_response"
                    attempt.error_message = "Tavily response has no results list"
                    return attempt, []
                attempt.raw_response = {key: value for key, value in response.items() if key != "answer"}
                attempt.request_id = response.get("request_id")
                attempt.response_time = float(response.get("response_time") or attempt.response_time or 0)
                credits = ((response.get("usage") or {}).get("credits"))
                attempt.credits_used = max(1, int(credits)) if isinstance(credits, (int, float)) else 1
                self.run_credits_used += attempt.credits_used
                if self.run_credits_used > self.config.max_credits_per_run:
                    self.disabled_for_run = True
                    attempt.status = "run_credit_limit_reached"
                    return attempt, []
                results = [TavilyResult(rank=index, title=_safe_text(item.get("title"), 500), url=_safe_text(item.get("url"), 2000),
                                        content=_safe_text(item.get("content"), 4000), score=item.get("score"),
                                        query_template_id=query.template_id, search_query=query.query,
                                        request_id=attempt.request_id, response_time=attempt.response_time,
                                        credits_used=attempt.credits_used)
                           for index, item in enumerate(response["results"], 1) if isinstance(item, dict) and item.get("url")]
                attempt.result_count = len(results)
                attempt.status = "candidates_found" if results else "no_results"
                return attempt, results
            retryable = status in {429, 500, 502, 503, 504} or response.get("_network_error") in {"timeout", "connection_error"}
            if status in {432, 433}:
                self.disabled_for_run = True
            if not retryable or number >= self.config.max_retries:
                attempt.status = self._status_for_http(status) if status else response.get("_network_error", "provider_error")
                attempt.error_type = attempt.status
                attempt.error_message = redact_secret(_error_message(response), self.config.api_key)
                return attempt, []
            time.sleep(self._retry_delay(headers, number))
        return attempt, []

    def map_confirmed_domain(self, domain: str) -> tuple[TavilyAttempt, list[str]]:
        """Map one already identified domain after access control blocks local HTML.

        This is not a discovery method and never follows external domains.  It
        is intentionally separate from :meth:`search` so callers can require
        a confirmed/probable local candidate and keep a complete audit trail.
        """
        attempt = TavilyAttempt(reason_for_call="ACCESS_CONTROL_RECOVERY", template_id="TAVILY_MAP_DOMAIN",
                                query=domain, include_domains=[domain])
        available, status = self.is_available()
        if not available or self.disabled_for_run:
            attempt.status = status if available is False else "free_quota_exhausted"
            return attempt, []
        payload = {"url": domain, "max_depth": 1, "max_breadth": 10, "limit": 20,
                   "select_domains": [f"^{re.escape(domain)}$"], "allow_external": False,
                   # Tavily Map accepts 10..150 seconds; the generic HTTP
                   # client timeout may legitimately be shorter.
                   "timeout": max(10.0, min(float(self.config.timeout_seconds), 150.0)), "include_usage": True}
        return self._simple_operation(MAP_ENDPOINT, payload, attempt, "results")

    def extract_public_pages(self, urls: list[str]) -> tuple[TavilyAttempt, list[str]]:
        """Extract at most five public, already selected URLs; no credentials or forms."""
        safe_urls = [url for url in urls if url.startswith(("https://", "http://"))][:5]
        attempt = TavilyAttempt(reason_for_call="ACCESS_CONTROL_RECOVERY", template_id="TAVILY_EXTRACT_PAGES",
                                query="; ".join(safe_urls), include_domains=[])
        available, status = self.is_available()
        if not available or self.disabled_for_run:
            attempt.status = status if available is False else "free_quota_exhausted"
            return attempt, []
        payload = {"urls": safe_urls, "extract_depth": "basic", "format": "text", "include_images": False,
                   "include_favicon": False, "timeout": min(float(self.config.timeout_seconds), 60.0), "include_usage": True}
        return self._simple_operation(EXTRACT_ENDPOINT, payload, attempt, "results")

    def _simple_operation(self, endpoint: str, payload: dict[str, Any], attempt: TavilyAttempt,
                          result_key: str) -> tuple[TavilyAttempt, list[str]]:
        if self.run_credits_used >= self.config.max_credits_per_run:
            attempt.status = "run_credit_limit_reached"
            return attempt, []
        try:
            started = time.monotonic()
            status, response, _headers = self._call_json(endpoint, payload)
            attempt.response_time = round(time.monotonic() - started, 3)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            attempt.status = "timeout" if isinstance(exc, TimeoutError) else "connection_error"
            attempt.error_message = redact_secret(str(exc), self.config.api_key)
            return attempt, []
        attempt.http_status = status
        if status != 200 or not isinstance(response, dict):
            attempt.status = self._status_for_http(status)
            attempt.error_message = redact_secret(_error_message(response, str(status)), self.config.api_key)
            if status in {432, 433}:
                self.disabled_for_run = True
            return attempt, []
        attempt.request_id = response.get("request_id")
        credits = ((response.get("usage") or {}).get("credits"))
        attempt.credits_used = max(1, int(credits)) if isinstance(credits, (int, float)) else 1
        self.run_credits_used += attempt.credits_used
        attempt.raw_response = response
        values = response.get(result_key)
        if not isinstance(values, list):
            attempt.status = "invalid_response"
            return attempt, []
        if endpoint == MAP_ENDPOINT:
            urls = [value for value in values if isinstance(value, str)]
        else:
            urls = [str(value.get("url")) for value in values if isinstance(value, dict) and value.get("url")]
        attempt.result_count = len(urls)
        attempt.status = "candidates_found" if urls else "no_results"
        if self.run_credits_used > self.config.max_credits_per_run:
            self.disabled_for_run = True
            attempt.status = "run_credit_limit_reached"
            return attempt, []
        return attempt, urls
