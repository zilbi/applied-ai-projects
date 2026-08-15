from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.classifier import classify_question
from src.ai.context_builder import build_context
from src.ai.gigachat_client import GigaChatClient
from src.models import AIConversation
from src.schemas import AIAskRequest, AIAskResponse


FINAL_SYSTEM_PROMPT = """Ты AI-помощник Customer Success Manager.
Отвечай только по переданному контексту.
Не выдумывай клиентов, даты, суммы и показатели.
Пиши кратко, структурировано и практически. Ответ не длиннее 1200-1500 символов.
Если данных не хватает, скажи, что нужно уточнить.
Всегда предлагай следующий шаг.
Не упоминай JSON, SQL, таблицы, repositories, context builder и внутреннюю архитектуру.

Структура ответа:
Кратко:
...

Почему важно:
...

Что сделать:
1. ...
2. ...
3. ...

Следующий шаг:
...

Для риска:
Проблема → причина → чек-лист действий → готовый следующий шаг.

Для гипотезы:
Проблема → 3–5 гипотез → шаги проверки → похожий кейс → кнопка/предложение создать задачу.

Для отчёта:
Краткий вывод → метрики → риски → рекомендации → действия CSM.
"""


async def ask_agent(session: AsyncSession, payload: AIAskRequest) -> AIAskResponse:
    client = GigaChatClient()
    classification = await classify_question(payload.question, client)
    category = classification.get("category", "unknown")
    context = await build_context(session, category, classification, payload.client_id)
    try:
        answer = client.chat(
            [
                {"role": "system", "content": FINAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Вопрос: {payload.question}\n\nКонтекст:\n{context}"},
            ]
        )
    except Exception as exc:
        answer = (
            "AI временно недоступен.\n"
            f"Причина: {type(exc).__name__}.\n"
            "Следующий шаг: проверьте GIGACHAT_API_KEY/сертификаты или повторите запрос позже."
        )
    conversation = AIConversation(
        user_id=payload.user_id,
        client_id=payload.client_id,
        channel=payload.channel,
        question=payload.question,
        answer=answer,
        category=category,
    )
    session.add(conversation)
    await session.commit()
    return AIAskResponse(category=category, classification=classification, answer=answer)
