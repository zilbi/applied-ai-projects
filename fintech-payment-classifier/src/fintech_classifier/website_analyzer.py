"""Bounded, same-domain analysis of a *confirmed* official website.

No model or LLM is involved: text weights, n-grams and phrase dictionaries are
deliberately transparent so a reviewer can see the source URL and context.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from . import enrichment
from .normalization import clean_text

MAX_SUBPAGES = 5
MAX_PAGES = 1 + MAX_SUBPAGES
ALGORITHM_VERSION = "website-text-v2"
# Real links from the home page are preferable to guessing URLs such as
# ``/contacts``.  Legal pages help verify the owner; business pages help
# analyse its operating model.  The score is deterministic and intentionally
# transparent in CLI diagnostics.
LINK_PRIORITIES = (
    ("реквиз", 100), ("requisit", 100), ("rekviz", 100),
    ("оферт", 95), ("offer", 95), ("услов", 90), ("terms", 90),
    ("документ", 85), ("document", 85), ("legal", 85),
    ("контакт", 80), ("contact", 80),
    ("продав", 75), ("seller", 75), ("merchant", 75), ("мерчант", 75),
    ("исполнител", 72), ("performer", 72), ("курьер", 72), ("courier", 72),
    ("партнер", 70), ("партнёр", 70), ("partner", 70),
    ("выплат", 68), ("payout", 68), ("расчет", 66), ("расчёт", 66), ("settlement", 66),
    ("комисс", 65), ("commission", 65), ("тариф", 63), ("tariff", 63),
    ("заказ", 62), ("order", 62), ("возврат", 60), ("refund", 60),
    ("платеж", 58), ("платёж", 58), ("payment", 58), ("эквайр", 58), ("acquiring", 58),
    ("api", 56), ("бизнес", 54), ("business", 54),
    ("услуг", 45), ("service", 45), ("продукт", 43), ("product", 43),
    ("решени", 42), ("solution", 42), ("о компани", 40), ("about", 40),
)
STOP = {"и", "в", "на", "с", "по", "для", "от", "до", "или", "это", "как", "мы", "вы", "ваш", "наш", "наши", "при", "а", "но", "не", "что", "из", "за", "the", "and", "for", "with", "наша", "ваши", "компания", "сайт", "политика", "cookie", "cookies", "copyright", "все", "услуги", "подробнее", "главная", "меню", "принять", "наверх", "телефон"}

# A family is evidence, not a final classification.  The hypothesis below
# requires two *different* families, so ten repetitions of one phrase do not
# become ten proofs.
SIGNAL_FAMILIES = {
    "PAYMENT_SERVICE": ("A1", ("приём платежей", "обработка платежей", "платёжный шлюз", "интернет-эквайринг", "процессинг", "оплата через api")),
    "THIRD_PARTY_FUNDS": ("A1", ("в пользу продавцов", "принимаем платежи ваших клиентов", "платежи в пользу третьих лиц", "расчёты с торговыми точками")),
    "COMMISSION_WITHHOLDING": ("A1", ("удержание комиссии", "выплата за вычетом комиссии", "комиссию из выплаты")),
    "PARTICIPANT_PAYOUT": ("B", ("выплаты продавцам", "выплаты исполнителям", "реестр выплат", "расчёты с партнёрами", "split", "payout")),
    "SETTLEMENT": ("A1", ("расчётный период", "merchant payout", "settlement")),
    "DIRECT_BUYER_TO_MERCHANT_PAYMENT": ("A2", ("покупатель платит продавцу напрямую", "платёж напрямую продавцу")),
    "SEPARATE_PLATFORM_COMMISSION": ("A2", ("продавец отдельно платит сервису комиссию", "отдельно оплачивает комиссию сервису")),
    "SERVICE_INTERMEDIATION": ("A2", ("сервис связывает покупателя и продавца", "сервис-посредник")),
    "INDEPENDENT_PARTICIPANTS": ("B", ("стать продавцом", "стать исполнителем", "личный кабинет продавца", "разместить товар", "независимые продавцы", "поставщики", "курьеры")),
    "PLATFORM_ORDER": ("B", ("заказ через платформу", "выбор продавца", "выбор исполнителя", "сравнение предложений", "бронирование через сервис")),
    "ORDER_MANAGEMENT": ("B", ("статус заказа", "отмена заказа", "возврат покупателю", "арбитраж", "безопасная сделка")),
    "PLATFORM_COMMISSION": ("B", ("комиссия площадки", "удержание комиссии платформы", "агентское вознаграждение")),
    "MULTI_SIDED_PLATFORM": ("B", ("покупатели и продавцы", "площадка объединяет покупателей и продавцов")),
    "OWN_PRODUCTS": ("NON_FINTECH", ("наши товары", "собственный склад", "наш интернет-магазин")),
    "OWN_SERVICES": ("NON_FINTECH", ("наши услуги", "наши клиники", "наши рестораны")),
    "OWN_STORES": ("NON_FINTECH", ("наши магазины",)),
    "OWN_PRODUCTION": ("NON_FINTECH", ("собственное производство",)),
    "DIRECT_RETAIL": ("NON_FINTECH", ("продаём собственные товары", "продажа собственных товаров")),
    "CARD_PAYMENT_ONLY": ("COUNTER", ("оплата картой", "принимаем банковские карты")),
    "SBP_PAYMENT_ONLY": ("COUNTER", ("оплата по сбп", "сбп")),
    "BANK_ACQUIRING_COMMISSION": ("COUNTER", ("комиссия банка за эквайринг",)),
    "GENERIC_PLATFORM_WORD": ("COUNTER", ("платформа",)),
    "GENERIC_PARTNER_WORD": ("COUNTER", ("партнёры", "партнеры")),
}


@dataclass
class AnalyzedPage:
    url: str
    depth: int
    html: str
    title: str = ""
    meta_description: str = ""
    h1: str = ""
    zones: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class WebsiteAnalysisResult:
    status: str
    pages: list[AnalyzedPage] = field(default_factory=list)
    keywords: list[dict] = field(default_factory=list)
    keyphrases: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    hypothesis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RelevantLink:
    """One same-domain link selected from the actually fetched page."""
    url: str
    text: str
    score: int
    matched_terms: tuple[str, ...]


@dataclass
class LinkSelection:
    selected: list[RelevantLink] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)


def _strip(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


class _VisibleTextParser(HTMLParser):
    """Collect data nodes only; attributes, JS and CSS are never page text."""
    ignored_tags = {"script", "style", "noscript", "svg", "template", "header", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        classes = " ".join(value or "" for key, value in attrs if key in {"class", "id", "aria-label"}).lower()
        if tag.lower() in self.ignored_tags or any(marker in classes for marker in ("cookie", "consent", "hidden")):
            self._ignored_tags.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tags and self._ignored_tags[-1] == tag.lower():
            self._ignored_tags.pop()

    def handle_data(self, data: str) -> None:
        if not self._ignored_tags and data.strip():
            self.parts.append(data)


def _visible_html_text(raw: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _extract(page: AnalyzedPage) -> None:
    raw = page.html
    page.title = _strip((re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S) or ["", ""])[1])
    meta = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", raw, re.I | re.S)
    page.meta_description = _strip(meta.group(1)) if meta else ""
    headings = {f"h{level}": [_strip(value) for value in re.findall(fr"<h{level}[^>]*>(.*?)</h{level}>", raw, re.I | re.S)] for level in (1, 2, 3)}
    json_ld: list[str] = []
    for block in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", raw, re.I | re.S):
        try:
            value = json.loads(html.unescape(block))
            def strings(item):
                if isinstance(item, str): return [item]
                if isinstance(item, list): return [text for child in item for text in strings(child)]
                if isinstance(item, dict): return [text for child in item.values() for text in strings(child)]
                return []
            json_ld.extend(strings(value))
        except (ValueError, TypeError):
            page.warnings.append("некорректный JSON-LD")
    page.h1 = " ".join(headings["h1"])
    # Do not parse anchors with a permissive regex: malformed third-party
    # markup (notably Tilda) can make it consume script/CSS tails as a button.
    # Visible body text still contains real CTA wording; a DOM-backed button
    # extractor can be added later without polluting the keyword corpus.
    buttons: list[str] = []
    page.zones = {"title": page.title, "meta": page.meta_description, "h1": page.h1,
                  "h2": " ".join(headings["h2"]), "h3": " ".join(headings["h3"]),
                  "buttons": " ".join(buttons), "json_ld": " ".join(json_ld), "body": _visible_html_text(raw)}


def _normal_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", ""))


def select_relevant_links(html_text: str, base_url: str, *, limit: int = MAX_SUBPAGES) -> LinkSelection:
    """Select useful same-domain pages from actual ``<a>`` elements.

    Both human-visible anchor text and URL path participate in the score.  It
    deliberately does not invent endpoints: an unavailable link is simply not
    followed, which avoids needless requests to non-existent legal paths.
    """
    base = _normal_url(base_url)
    base_domain = urllib.parse.urlsplit(base).netloc
    skipped: Counter[str] = Counter()
    by_url: dict[str, RelevantLink] = {}
    for attrs, body in re.findall(r"<a\b([^>]*)>(.*?)</a\s*>", html_text, re.I | re.S):
        href_match = re.search(r"\bhref\s*=\s*([\"'])(.*?)\1", attrs, re.I | re.S)
        if not href_match:
            skipped["without_href"] += 1
            continue
        href = html.unescape(href_match.group(2)).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            skipped["technical_link"] += 1
            continue
        target = _normal_url(urllib.parse.urljoin(base, href))
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_domain:
            skipped["external_domain"] += 1
            continue
        lowered = target.lower()
        if any(item in lowered for item in ("/search", "/calendar", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".jpg", ".jpeg", ".png", ".svg", ".mp4")):
            skipped["non_html_or_unbounded"] += 1
            continue
        if target.rstrip("/") == base.rstrip("/"):
            skipped["home_duplicate"] += 1
            continue
        label = _strip(body)
        searchable = f"{label} {urllib.parse.urlsplit(target).path}".lower()
        matched = tuple(term for term, _weight in LINK_PRIORITIES if term in searchable)
        if not matched:
            skipped["not_relevant"] += 1
            continue
        score = max(weight for term, weight in LINK_PRIORITIES if term in searchable)
        item = RelevantLink(target, label or urllib.parse.urlsplit(target).path, score, matched)
        previous = by_url.get(target)
        if previous is None or item.score > previous.score:
            by_url[target] = item
        else:
            skipped["duplicate"] += 1
    selected = sorted(by_url.values(), key=lambda item: (-item.score, item.url))[:max(0, limit)]
    return LinkSelection(selected=selected, skipped=dict(sorted(skipped.items())))


def _links(page: AnalyzedPage, base_domain: str) -> list[str]:
    """Compatibility helper retained for callers that only need URLs."""
    if urllib.parse.urlsplit(page.url).netloc != base_domain:
        return []
    return [item.url for item in select_relevant_links(page.html, page.url).selected]


def crawl_confirmed_site(url: str, *, fetcher: Callable[[str], str] = enrichment._fetch, max_pages: int = MAX_PAGES) -> WebsiteAnalysisResult:
    root = _normal_url(url)
    pages: list[AnalyzedPage] = []
    warnings: list[str] = []
    try:
        payload = fetcher(root)
    except Exception as exc:
        return WebsiteAnalysisResult("insufficient_content", warnings=[f"{root}: {type(exc).__name__}: {exc}"])
    if not payload:
        return WebsiteAnalysisResult("insufficient_content", warnings=[f"{root}: пустой ответ"])
    home = AnalyzedPage(root, 0, payload)
    _extract(home)
    pages.append(home)
    selection = select_relevant_links(payload, root, limit=max(0, max_pages - 1))
    if selection.selected:
        warnings.append("выбраны реальные ссылки: " + "; ".join(f"{item.url} ({item.score})" for item in selection.selected))
    if selection.skipped:
        warnings.append("исключены ссылки: " + ", ".join(f"{reason}={count}" for reason, count in selection.skipped.items()))
    for link in selection.selected:
        try:
            payload = fetcher(link.url)
        except Exception as exc:
            warnings.append(f"{link.url}: {type(exc).__name__}: {exc}")
            continue
        if not payload:
            warnings.append(f"{link.url}: пустой ответ")
            continue
        page = AnalyzedPage(link.url, 1, payload)
        _extract(page)
        pages.append(page)
    return WebsiteAnalysisResult("success" if pages else "insufficient_content", pages=pages, warnings=warnings)


def _looks_like_waf(html_text: str) -> bool:
    value = html_text.lower()
    return any(marker in value for marker in ("please enable javascript", "access denied", "akamai", "cloudflare", "/tspd/", "bobcmn", "user_blocked"))


def analyze_local_html(paths: list[Path], *, company_name: str | None = None, inn: str | None = None,
                       domain: str | None = None) -> WebsiteAnalysisResult:
    """Analyze fixture/snapshot HTML without opening a network connection."""
    pages: list[AnalyzedPage] = []
    warnings: list[str] = []
    for path in sorted(paths):
        raw = path.read_text(encoding="utf-8", errors="replace")
        if _looks_like_waf(raw):
            return WebsiteAnalysisResult("skipped", warnings=[f"{path.name}: blocked_by_waf"])
        page = AnalyzedPage(url=f"file://{path.name}", depth=0, html=raw)
        _extract(page)
        if not any(page.zones.values()):
            warnings.append(f"{path.name}: пустой HTML")
            continue
        pages.append(page)
    if not pages:
        return WebsiteAnalysisResult("insufficient_content", warnings=warnings or ["нет пригодных HTML-страниц"])
    result = WebsiteAnalysisResult("success", pages=pages, warnings=warnings)
    result.keywords, result.keyphrases = extract_keywords(pages, company_name, inn)
    result.signals = extract_signals(pages)
    result.hypothesis = website_hypothesis(result.signals)
    return result


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[а-яёa-z][а-яёa-z0-9-]{2,}", clean_text(text).lower()) if word not in STOP and not word.isdigit()]


def extract_keywords(pages: list[AnalyzedPage], company_name: str | None = None, inn: str | None = None) -> tuple[list[dict], list[dict]]:
    scores: dict[tuple[str, str], float] = Counter(); occurrences: Counter = Counter(); urls: defaultdict = defaultdict(set); contexts: defaultdict = defaultdict(list)
    company_words = set(_words(company_name or ""))
    zone_weights = {"title": 5, "meta": 4, "h1": 5, "h2": 4, "h3": 3, "buttons": 3, "json_ld": 3, "body": 1}
    for page in pages:
        for zone, text in page.zones.items():
            words = _words(text)
            for size in range(1, 5):
                for index in range(len(words) - size + 1):
                    phrase = " ".join(words[index:index + size])
                    if any(word in company_words for word in phrase.split()) or (inn and inn in phrase) or len(phrase) < 4:
                        continue
                    kind = "keyword" if size == 1 else "keyphrase"
                    key = (kind, phrase)
                    scores[key] += zone_weights[zone]
                    occurrences[key] += 1
                    urls[key].add(page.url)
                    if len(contexts[key]) < 3:
                        contexts[key].append(text[max(0, text.lower().find(phrase) - 80):text.lower().find(phrase) + len(phrase) + 120])
    output = []
    for (kind, phrase), score in scores.items():
        # Require a little evidence for a body-only accidental n-gram.
        if score < (2 if kind == "keyword" else 3):
            continue
        output.append({"keyword_type": kind, "text": phrase, "normalized_text": clean_text(phrase).lower(), "score": round(score, 2),
                       "occurrences": occurrences[(kind, phrase)], "page_urls": sorted(urls[(kind, phrase)]),
                       "page_sources": sorted(urls[(kind, phrase)]), "contexts": contexts[(kind, phrase)]})
    output.sort(key=lambda item: (-item["score"], -len(item["page_urls"]), item["text"]))
    return [item for item in output if item["keyword_type"] == "keyword"][:20], [item for item in output if item["keyword_type"] == "keyphrase"][:15]


def extract_signals(pages: list[AnalyzedPage]) -> list[dict]:
    # Navigation/footer text is often copied verbatim to every page.  One
    # phrase therefore remains one evidence item with occurrence metadata,
    # rather than becoming linear rule weight through a crawl.
    by_key: dict[tuple[str, str, str], dict] = {}
    for page in pages:
        for zone, text in page.zones.items():
            normalized = clean_text(text).lower()
            for family, (pre_class, phrases) in SIGNAL_FAMILIES.items():
                for phrase in phrases:
                    if phrase not in normalized:
                        continue
                    context = text[max(0, normalized.find(phrase) - 100):normalized.find(phrase) + len(phrase) + 160]
                    normalized_context = clean_text(context).lower()
                    key = (family, phrase, normalized_context)
                    index = normalized.find(phrase)
                    if key in by_key:
                        item = by_key[key]
                        item["occurrence_count"] += 1
                        item["source_urls"] = sorted(set(item["source_urls"] + [page.url]))
                        item["independent_page_count"] = len(item["source_urls"])
                        # Keep a high-value heading occurrence, but never add
                        # its weight a second time.
                        if zone in {"title", "h1", "h2"}:
                            item["weight"] = max(item["weight"], 2.0)
                            item["html_zone"] = zone
                        continue
                    by_key[key] = {"signal_family": family, "signal_code": family.lower(), "preliminary_class": pre_class,
                                   "matched_phrase": phrase, "normalized_phrase": phrase, "context": context,
                                   "page_url": page.url, "page_source": page.url, "html_zone": zone,
                                   "weight": 2.0 if zone in {"title", "h1", "h2"} else 1.0,
                                   "occurrence_count": 1, "source_urls": [page.url], "independent_page_count": 1}
    return list(by_key.values())


def website_hypothesis(signals: list[dict]) -> dict:
    """Make a transparent website-only hypothesis; never a company class."""
    families: dict[str, set[str]] = defaultdict(set)
    evidence: dict[str, list[dict]] = defaultdict(list)
    counters: list[dict] = []
    for signal in signals:
        kind = signal["preliminary_class"]
        if kind == "COUNTER":
            counters.append(signal)
        else:
            families[kind].add(signal["signal_family"])
            evidence[kind].append(signal)
    counts = {kind: len(value) for kind, value in families.items()}
    strong = {kind for kind in ("A1", "A2", "B") if counts.get(kind, 0) >= 2}
    if len(strong) != 1:
        # A site that explicitly sells its own goods/services is allowed to be
        # a non-fintech hypothesis even if all ownership phrases map to one
        # family.  Payment-by-card wording remains only counter-evidence.
        kind = "NON_FINTECH" if counts.get("NON_FINTECH", 0) >= 1 and not strong else "REVIEW"
    else:
        kind = next(iter(strong))
    score = round(sum(item["weight"] for item in evidence.get(kind, [])), 2)
    return {
        "website_hypothesis": kind,
        "scores": {name: round(sum(item["weight"] for item in entries), 2) for name, entries in evidence.items()},
        "evidence": evidence.get(kind, []),
        "counter_evidence": counters,
        "missing_evidence": [] if kind != "REVIEW" else ["для A1, A2 или B нужны минимум два независимых семейства сигналов"],
        "reason": f"независимые семейства для {kind}: {sorted(families.get(kind, set()))}" if kind != "REVIEW" else "недостаточно независимых либо конфликтующих семейств сигналов",
        "score": score,
    }


def save_analysis(store, company_id: int, website_id: int, inn: str | None, domain: str, result: WebsiteAnalysisResult,
                  company_name: str | None = None, snapshot_root: str | Path = "results/website_snapshots") -> WebsiteAnalysisResult:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(snapshot_root) / (inn or "unverified") / domain / stamp
    root.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(result.pages, 1):
        content_hash = hashlib.sha256(page.html.encode("utf-8", errors="replace")).hexdigest()
        html_path, text_path = root / f"{index:02d}_{content_hash[:12]}.html", root / f"{index:02d}_{content_hash[:12]}.txt"
        html_path.write_text(page.html, encoding="utf-8")
        text_path.write_text(page.zones.get("body", ""), encoding="utf-8")
        store.add_website_page(website_id, company_id, url=page.url, page_type="priority" if page.depth else "home", http_status=200,
                               title=page.title, meta_description=page.meta_description, h1=page.h1, visible_text_path=str(text_path),
                               html_snapshot_path=str(html_path), content_hash=content_hash, parse_status="parsed", warnings=page.warnings)
    result.keywords, result.keyphrases = extract_keywords(result.pages, company_name, inn)
    store.replace_website_keywords(company_id, website_id, result.keywords + result.keyphrases, ALGORITHM_VERSION)
    result.signals = extract_signals(result.pages)
    result.hypothesis = website_hypothesis(result.signals)
    for signal in result.signals:
        store.add_website_signal(company_id, website_id, family=signal["signal_family"], code=signal["signal_code"],
                                 preliminary_class=signal["preliminary_class"], phrase=signal["matched_phrase"],
                                 normalized_phrase=signal["normalized_phrase"], context=signal["context"], page_url=signal["page_url"],
                                 html_zone=signal["html_zone"], weight=signal["weight"], algorithm_version=ALGORITHM_VERSION,
                                 occurrence_count=signal.get("occurrence_count", 1), source_urls=signal.get("source_urls"),
                                 independent_page_count=signal.get("independent_page_count", 1))
    return result
