def build_local_answer(intent: str, context: dict) -> str:
    clients = context.get("clients", [])
    tasks = context.get("tasks", [])
    deals = context.get("deals", [])
    meetings = context.get("meetings", [])
    metrics = context.get("metrics", [])
    recommendations = context.get("recommendations", [])

    facts = []
    risks = []
    actions = []

    if clients:
        risky = [c for c in clients if c.get("risk_level") in {"high", "medium"}]
        facts.append(f"Клиентов в контексте: {len(clients)}.")
        if risky:
            risks.append("В зоне риска: " + ", ".join(c.get("name", "") for c in risky[:5]))
        for client in clients[:3]:
            reason = client.get("risk_reasons") or "явных причин риска в контексте нет"
            facts.append(f"{client.get('name')}: health {client.get('health_score')}, риск {client.get('risk_level')} {client.get('risk_score_local')}; {reason}.")

    if tasks:
        overdue = [t for t in tasks if t.get("status") == "overdue"]
        facts.append(f"Задач в контексте: {len(tasks)}.")
        if overdue:
            risks.append(f"Просроченных задач: {len(overdue)}.")
        actions.extend(f"Разобрать задачу: {t.get('title')} ({t.get('due_date')})." for t in tasks[:3])

    if deals:
        no_offer = [d for d in deals if not d.get("commercial_offer_exists")]
        facts.append(f"Сделок в контексте: {len(deals)}.")
        if no_offer:
            risks.append(f"Сделок без КП: {len(no_offer)}.")
        actions.extend(f"Проверить сделку: {d.get('name')} / {d.get('stage')}." for d in deals[:3])

    if meetings:
        facts.append(f"Встреч в контексте: {len(meetings)}.")
        actions.extend(f"Подготовиться к встрече: {m.get('title')} {m.get('meeting_datetime')}." for m in meetings[:3])

    if metrics:
        facts.append(f"Метрик в контексте: {len(metrics)}.")
        bad = [m for m in metrics if m.get("risk_score", 0) >= 60]
        if bad:
            risks.append("Высокий risk score по метрикам: " + ", ".join(m.get("client", "") for m in bad[:4]))

    if recommendations:
        actions.extend(recommendations[:3])

    if not facts:
        facts.append("По локальной базе не найдено достаточно фактов для точного ответа.")
        actions.append("Уточните клиента, задачи, сделки, встречи, риски или показатели.")

    title = {
        "client_summary": "Сводка по клиенту",
        "risk_overview": "Обзор рисков",
        "tasks_overview": "Обзор задач",
        "deals_overview": "Обзор сделок",
        "meetings_overview": "Обзор встреч",
        "metrics_overview": "Обзор показателей",
        "daily_digest": "Ежедневная сводка",
        "fallback": "Уточнение запроса",
    }.get(intent, "Ответ ассистента")

    return "\n".join([
        f"{title}.",
        "Краткий вывод: " + (risks[0] if risks else facts[0]),
        "Факты из БД:",
        *[f"- {item}" for item in facts[:6]],
        "Риски:",
        *([f"- {item}" for item in risks[:5]] or ["- Критичные риски в выбранном контексте не найдены."]),
        "Рекомендации:",
        *([f"- {item}" for item in actions[:5]] or ["- Проверьте карточки клиентов и актуальность данных."]),
    ])
