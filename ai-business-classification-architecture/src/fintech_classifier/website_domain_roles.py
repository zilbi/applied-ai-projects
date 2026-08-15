"""Central, deterministic classification of public website-search results."""
from __future__ import annotations

import re
import urllib.parse
from enum import Enum


class DomainRole(str, Enum):
    OFFICIAL_CANDIDATE = "official_candidate"
    REGISTRY_DIRECTORY = "registry_directory"
    WIKIPEDIA = "wikipedia"
    SOCIAL_NETWORK = "social_network"
    APP_STORE = "app_store"
    MARKETPLACE_CARD = "marketplace_card"
    THIRD_PARTY_COMPANY_CARD = "third_party_company_card"
    MULTITENANT_STOREFRONT = "multitenant_storefront"
    ACADEMIC_PROFILE = "academic_profile"
    BENEFITS_CATALOG = "benefits_catalog"
    MEDIA = "media"
    JOB_SITE = "job_site"
    MAPS = "maps"
    RATING_AGGREGATOR = "rating_aggregator"
    EDUCATION_AGGREGATOR = "education_aggregator"
    PROJECT_OR_EVENT = "project_or_event"
    UNKNOWN = "unknown"
    UNRELATED = "unrelated"


HARD_REJECT_ROLES = {
    DomainRole.REGISTRY_DIRECTORY, DomainRole.WIKIPEDIA, DomainRole.SOCIAL_NETWORK,
    DomainRole.APP_STORE, DomainRole.MARKETPLACE_CARD, DomainRole.MEDIA,
    DomainRole.JOB_SITE, DomainRole.MAPS, DomainRole.RATING_AGGREGATOR,
    DomainRole.EDUCATION_AGGREGATOR, DomainRole.THIRD_PARTY_COMPANY_CARD,
    DomainRole.MULTITENANT_STOREFRONT, DomainRole.ACADEMIC_PROFILE,
    DomainRole.BENEFITS_CATALOG, DomainRole.PROJECT_OR_EVENT, DomainRole.UNRELATED,
}
REGISTRY_DIRECTORY_DOMAINS = {
    # Контур/Фокус — карточки контрагентов, а не официальные сайты исследуемых
    # компаний. Это абсолютный запрет: совпадающие ИНН/ОГРН описывают профиль
    # компании в сервисе Контур, а не владельца домена.
    "kontur.ru", "kontur.tech", "kontur-fokus.ru",
    "checko.ru", "zachestnyibiznes.ru", "rusprofile.ru", "companies.rbc.ru",
    "sbis.ru", "list-org.com", "audit-it.ru", "spark-interfax.ru", "e-disclosure.ru", "finmarket.ru",
    "ra-national.ru", "raexpert.ru", "bankiros.ru", "xfirm.ru", "b2b-center.ru", "nalog.ru", "rkn.gov.ru",
}
WIKIPEDIA_DOMAINS = {"wikipedia.org"}
APP_STORE_DOMAINS = {"play.google.com", "apps.apple.com", "appgallery.huawei.com", "apps.microsoft.com", "rustore.ru", "apkpure.com"}
SOCIAL_DOMAINS = {"vk.com", "ok.ru", "facebook.com", "instagram.com", "linkedin.com", "t.me", "telegram.me", "telegram.org", "youtube.com", "youtu.be", "rutube.ru", "tiktok.com", "x.com", "twitter.com"}
JOB_DOMAINS = {"hh.ru", "career.habr.com", "superjob.ru", "rabota.ru"}
MAP_DOMAINS = {"2gis.ru", "maps.yandex.ru"}
MEDIA_DOMAINS = {"rbc.ru", "tass.ru", "interfax.ru", "kommersant.ru", "vedomosti.ru", "forbes.ru"}
RATING_DOMAINS = {"rsr-online.ru", "raex-a.ru", "raexpert.ru", "ra-national.ru", "retail.ru", "tadviser.ru", "iossro37.ru", "gidvuz.com"}
EDUCATION_DOMAINS = {"postupi.online", "vuzopedia.ru", "tabiturient.ru"}
MARKETPLACE_DOMAINS = {"ozon.ru", "wildberries.ru", "avito.ru", "aliexpress.ru", "market.yandex.ru", "cibum.ru"}
ACADEMIC_DOMAINS = {"nature.com", "researchgate.net", "scopus.com"}
BENEFITS_DOMAINS = {"bestbenefits.ru", "benefits.ru"}


def _matches(domain: str, values: set[str]) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in values)


def classify_domain_role(url: str, *, title: str | None = None, snippet: str | None = None) -> tuple[DomainRole, str]:
    """Return role/reason before any company identifier is inspected."""
    parsed = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    domain, path = parsed.netloc.lower().split(":")[0], parsed.path.lower()
    text = " ".join((title or "", snippet or "")).lower()
    if _matches(domain, WIKIPEDIA_DOMAINS): return DomainRole.WIKIPEDIA, "wikipedia_domain"
    if _matches(domain, APP_STORE_DOMAINS) or "/store/" in path and "google" in domain: return DomainRole.APP_STORE, "app_store_domain_or_path"
    if _matches(domain, SOCIAL_DOMAINS): return DomainRole.SOCIAL_NETWORK, "social_domain"
    if _matches(domain, JOB_DOMAINS): return DomainRole.JOB_SITE, "job_domain"
    # A careers portal may use the employer's own domain (for example a
    # ``rabota.*`` subdomain).  It is genuine employer content, but it is not
    # the legal/public company website and must never win site selection.
    career_markers = ("ваканси", "стажировк", "карьер", "работа в ", "работа у ", "присоединиться к команде")
    if (re.search(r"(^|\.)(career|careers|rabota|job|jobs|vacancy)\.", domain)
            or re.search(r"/(career|careers|rabota|job|jobs|vacancy|vakans)", path)
            or sum(marker in text for marker in career_markers) >= 2):
        return DomainRole.PROJECT_OR_EVENT, "career_or_recruitment_page"
    # A regular Google/Yandex result is not a map card.  Blocking the whole
    # provider domain would make the classifier depend on a fragile URL shape.
    if _matches(domain, MAP_DOMAINS) or "/maps" in path: return DomainRole.MAPS, "maps_domain_or_path"
    if _matches(domain, REGISTRY_DIRECTORY_DOMAINS): return DomainRole.REGISTRY_DIRECTORY, "registry_or_directory_domain"
    if _matches(domain, RATING_DOMAINS) or any(item in text for item in ("рейтинг компаний", "рейтинг университет", "сравнение вузов", "топ компаний")):
        return DomainRole.RATING_AGGREGATOR, "rating_aggregator"
    if _matches(domain, EDUCATION_DOMAINS) or any(item in text for item in ("поступление в вуз", "абитуриент", "каталог вузов")):
        return DomainRole.EDUCATION_AGGREGATOR, "education_aggregator"
    if _matches(domain, MEDIA_DOMAINS): return DomainRole.MEDIA, "media_domain"
    if _matches(domain, ACADEMIC_DOMAINS):
        return DomainRole.ACADEMIC_PROFILE, "academic_profile_domain"
    if _matches(domain, BENEFITS_DOMAINS) and re.search(r"/(product|catalog|benefit|offer)/", path):
        return DomainRole.BENEFITS_CATALOG, "benefits_catalog_path"
    if _matches(domain, {"cibum.ru"}) and re.search(r"/(seller|shop|store|product|catalog|brands|aboutshop|item)/", path):
        return DomainRole.THIRD_PARTY_COMPANY_CARD, "third_party_company_card_path"
    if _matches(domain, MARKETPLACE_DOMAINS) and re.search(r"/(seller|shop|store|product|catalog|brands|aboutshop|item)/", path):
        return DomainRole.MARKETPLACE_CARD, "marketplace_card_path"
    if any(item in text for item in ("conference", "forum", "event", "олимпиада", "конференция", "мероприятие", "регистрация участников")):
        return DomainRole.PROJECT_OR_EVENT, "event_or_project_page"
    if not domain: return DomainRole.UNRELATED, "missing_domain"
    return DomainRole.OFFICIAL_CANDIDATE, "no_third_party_markers"
