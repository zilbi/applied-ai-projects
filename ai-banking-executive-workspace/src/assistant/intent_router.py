INTENT_CLIENT_SUMMARY = "client_summary"
INTENT_RISK_OVERVIEW = "risk_overview"
INTENT_TASKS_OVERVIEW = "tasks_overview"
INTENT_DEALS_OVERVIEW = "deals_overview"
INTENT_MEETINGS_OVERVIEW = "meetings_overview"
INTENT_METRICS_OVERVIEW = "metrics_overview"
INTENT_DAILY_DIGEST = "daily_digest"
INTENT_FALLBACK = "fallback"

CATEGORY_SUMMARY = "summary"
CATEGORY_CLIENTS = "clients"
CATEGORY_TASKS = "tasks"
CATEGORY_DEALS = "deals"
CATEGORY_MEETINGS = "meetings"
CATEGORY_METRICS = "metrics"
CATEGORY_RISKS = "risks"
CATEGORY_MESSAGES = "messages"
CATEGORY_FALLBACK = "fallback"


def detect_category(question: str) -> str:
    text = (question or "").lower()
    if not text.strip():
        return CATEGORY_FALLBACK

    if any(word in text for word in ("клиент", "клиентом", "клиенту", "проблемные клиенты", "давно не было контакта")):
        return CATEGORY_CLIENTS
    if any(word in text for word in ("задач", "просроч", "исполнитель", "менеджер", "дедлайн", "blocked", "блок")):
        return CATEGORY_TASKS
    if any(word in text for word in ("сделк", "кп", "коммерческ", "proposal", "завис", "воронк")):
        return CATEGORY_DEALS
    if any(word in text for word in ("встреч", "календар", "готовиться", "сегодня встреч", "созвон")):
        return CATEGORY_MEETINGS
    if any(word in text for word in ("показател", "метрик", "план", "факт", "nps", "risk score", "activity", "активити", "выруч")):
        return CATEGORY_METRICS
    if any(word in text for word in ("риск", "риски", "проблем", "требует внимания", "что требует внимания", "угроз")):
        return CATEGORY_RISKS
    if any(word in text for word in ("сообщ", "уведом", "что пришло", "не прочит", "непрочит", "system_alert", "task_update", "new_task", "risk_alert")):
        return CATEGORY_MESSAGES
    if any(word in text for word in ("summary", "свод", "что происходит", "что важно", "краткую картину", "картина", "обзор")):
        return CATEGORY_SUMMARY
    return CATEGORY_FALLBACK


def detect_intent(question: str) -> str:
    category = detect_category(question)
    if category == CATEGORY_SUMMARY:
        return INTENT_DAILY_DIGEST
    if category == CATEGORY_CLIENTS:
        return INTENT_CLIENT_SUMMARY
    if category == CATEGORY_TASKS:
        return INTENT_TASKS_OVERVIEW
    if category == CATEGORY_DEALS:
        return INTENT_DEALS_OVERVIEW
    if category == CATEGORY_MEETINGS:
        return INTENT_MEETINGS_OVERVIEW
    if category == CATEGORY_METRICS:
        return INTENT_METRICS_OVERVIEW
    if category == CATEGORY_RISKS:
        return INTENT_RISK_OVERVIEW
    if category == CATEGORY_MESSAGES:
        return INTENT_FALLBACK

    text = (question or "").lower()
    if any(word in text for word in ("ежеднев", "важно сегодня", "дайджест")):
        return INTENT_DAILY_DIGEST
    if any(word in text for word in ("зоне риска", "требует внимания", "самые большие проблемы", "где проблемы")):
        return INTENT_RISK_OVERVIEW
    if any(word in text for word in ("клиент", "клиентом", "клиенту")) and any(word in text for word in ("свод", "риск", "происходит", "статус")):
        return INTENT_CLIENT_SUMMARY
    if any(word in text for word in ("зоне риска", "требует внимания", "проблем", "риск", "риски")):
        return INTENT_RISK_OVERVIEW
    if any(word in text for word in ("задач", "просроч", "менеджер", "сегодня сделать", "нужно сделать")):
        return INTENT_TASKS_OVERVIEW
    if any(word in text for word in ("сделк", "кп", "proposal", "завис")):
        return INTENT_DEALS_OVERVIEW
    if any(word in text for word in ("встреч", "подготов", "ближайш")):
        return INTENT_MEETINGS_OVERVIEW
    if any(word in text for word in ("показател", "метрик", "план", "факт", "просел", "ухудш")):
        return INTENT_METRICS_OVERVIEW
    return INTENT_FALLBACK
