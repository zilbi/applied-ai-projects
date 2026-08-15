from __future__ import annotations

from .features import A_MARKERS, B_MARKERS, NON_FINTECH_MARKERS, build_features
from .schemas import WebsiteResult

CLASSES = ("A — платёжный посредник", "B — платформа / marketplace", "Не финтех")


def score_rules(group, website: WebsiteResult) -> tuple[dict[str, float], dict[str, list[str]], dict[str, list[str]]]:
    f = build_features(group)
    website_text = " ".join(website.evidence).upper()
    a, b, n = 0.0, 0.0, 0.0
    evidence = {label: [] for label in CLASSES}
    counter = {label: [] for label in CLASSES}
    if f["a_marker_share"] >= .15:
        a += .28; evidence[CLASSES[0]].append("назначения содержат устойчивые маркеры эквайринга/реестра/payout")
    if f["net_settlement_ratio"] >= .25:
        a += .30; evidence[CLASSES[0]].append("обнаружен повторяемый gross → payout / net settlement паттерн")
    if f["fee_share"] >= .10:
        a += .14; evidence[CLASSES[0]].append("в назначениях регулярно встречается комиссия")
    if f["identifier_share"] >= .20:
        a += .10; evidence[CLASSES[0]].append("есть технические идентификаторы order/merchant/register")
    if any(x in website_text for x in A_MARKERS):
        a += .28; evidence[CLASSES[0]].append("подтверждённый сайт описывает платёжную услугу")
    if f["b_marker_share"] >= .15:
        b += .26; evidence[CLASSES[1]].append("назначения содержат маркеры продавцов/исполнителей/заказов")
    if f["has_two_sided_flow"] and f["out_count"] >= 3 and f["counterparties"] >= 4:
        b += .20; evidence[CLASSES[1]].append("наблюдается многосторонний поток с выплатами контрагентам")
    if f["identifier_share"] >= .15 and f["net_settlement_ratio"] >= .15:
        b += .18; evidence[CLASSES[1]].append("заказы связаны с последующими выплатами")
    if any(x in website_text for x in B_MARKERS):
        b += .30; evidence[CLASSES[1]].append("подтверждённый сайт описывает платформенную модель")
    if f["non_fintech_marker_share"] >= .15:
        n += .28; evidence[CLASSES[2]].append("назначения соответствуют собственной операционной деятельности")
    if not f["has_two_sided_flow"]:
        n += .12; evidence[CLASSES[2]].append("не наблюдается устойчивая двусторонняя транзитная схема")
    if any(x in website_text for x in NON_FINTECH_MARKERS):
        n += .32; evidence[CLASSES[2]].append("подтверждённый сайт описывает собственный товар или услугу")
    if f["fee_share"] > 0 and f["a_marker_share"] < .10 and f["net_settlement_ratio"] == 0:
        n += .15; evidence[CLASSES[2]].append("комиссия выглядит расходом пользователя эквайринга, а не его продуктом")
    if f["operations"] < 5:
        for label in CLASSES: counter[label].append("менее пяти операций")
    if not website.url:
        for label in CLASSES: counter[label].append("официальный сайт не подтверждён")
    return ({CLASSES[0]: min(a, 1), CLASSES[1]: min(b, 1), CLASSES[2]: min(n, 1)}, evidence, counter)
