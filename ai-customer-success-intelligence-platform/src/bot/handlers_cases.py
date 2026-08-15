from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

from src.ai.agent_service import ask_agent
from src.bot.formatters import compact_ai_answer
from src.bot.handlers_ai import set_pending_ai_context
from src.bot.keyboards import back_home_keyboard, case_detail_keyboard, cases_keyboard
from src.db import SessionLocal
from src.schemas import AIAskRequest


router = Router()


CASES = {
    "medicine": {
        "title": "🏥 ИИ в медицине",
        "situation": "клиника хочет быстрее обрабатывать обращения пациентов, снижать нагрузку на администраторов и не терять повторные визиты.",
        "bot": "показывает риски по клиенту, помогает сформулировать сценарии ИИ: запись на приём, напоминания, первичная маршрутизация и контроль удовлетворённости.",
        "result": "CSM видит понятный план внедрения ИИ для клиники и может предложить следующий шаг без долгой подготовки.",
    },
    "realty": {
        "title": "🏢 ИИ в недвижимости",
        "situation": "агентство или девелопер хочет быстрее квалифицировать лиды, подбирать объекты и возвращать клиентов к сделке.",
        "bot": "собирает контекст клиента, предлагает сценарии ИИ для подбора объектов, follow-up сообщений, приоритизации лидов и прогноза риска срыва сделки.",
        "result": "CSM показывает клиенту, где ИИ сразу влияет на скорость продаж и качество коммуникации.",
    },
    "retail": {
        "title": "🛒 ИИ в ритейле",
        "situation": "ритейл-клиент хочет лучше понимать спрос, удерживать покупателей и быстрее реагировать на падение активности.",
        "bot": "помогает CSM связать метрики клиента с AI-сценариями: персональные предложения, прогноз спроса, анализ отзывов и предотвращение оттока.",
        "result": "CSM получает короткую историю ценности ИИ для ритейла и готовые аргументы для встречи.",
    },
    "finance": {
        "title": "💳 ИИ в финансах",
        "situation": "банк, финтех или страховая компания хочет ускорить поддержку, повысить качество консультаций и лучше управлять рисками.",
        "bot": "подсказывает сценарии ИИ: умный помощник оператора, анализ обращений, выявление риск-сигналов и подготовка персональных коммуникаций.",
        "result": "CSM быстро объясняет клиенту, как ИИ помогает снижать операционную нагрузку и повышать качество сервиса.",
    },
    "logistics": {
        "title": "🚚 ИИ в логистике",
        "situation": "логистическая компания хочет быстрее обрабатывать заявки, прогнозировать задержки и держать клиентов в курсе статуса.",
        "bot": "помогает сформировать AI-сценарии: прогноз задержек, автоответы по статусу доставки, приоритизация проблемных заказов и анализ причин сбоев.",
        "result": "CSM показывает клиенту практический план, где ИИ снижает ручную работу и повышает прозрачность сервиса.",
    },
    "education": {
        "title": "🎓 ИИ в образовании",
        "situation": "онлайн-школа или вуз хочет удерживать студентов, быстрее отвечать на вопросы и видеть, кто рискует бросить обучение.",
        "bot": "предлагает сценарии ИИ: помощник студента, анализ прогресса, напоминания, персональные рекомендации и выявление риска оттока.",
        "result": "CSM получает понятный набор идей, как показать ценность ИИ образовательному клиенту.",
    },
}


@router.callback_query(lambda c: c.data == "cases")
async def cases_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "📚 Кейсы CSM\n\n"
        "Здесь собраны отраслевые сценарии применения ИИ. "
        "Можно быстро понять, какую ценность CSM Pulse помогает показать клиенту.\n\n"
        "Откройте кейс, нажмите AI-кнопку и уточняйте вопрос текстом или голосом 🎙",
        reply_markup=cases_keyboard(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("case:"))
async def case_detail_callback(callback: CallbackQuery) -> None:
    case_key = callback.data.split(":", 1)[1]
    case = CASES.get(case_key)
    if not case:
        await callback.answer("Кейс не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_case_text(case), reply_markup=case_detail_keyboard(case_key))


@router.callback_query(lambda c: c.data and c.data.startswith("case_ai:"))
async def case_ai_callback(callback: CallbackQuery) -> None:
    case_key = callback.data.split(":", 1)[1]
    case = CASES.get(case_key)
    if not case:
        await callback.answer("Кейс не найден", show_alert=True)
        return
    await callback.answer("Спрашиваю AI...")
    question = (
        f"Расскажи CSM коротко и практично про кейс CSM Pulse: {case['title']}.\n"
        f"Ситуация: {case['situation']}\n"
        f"Что делает бот: {case['bot']}\n"
        f"Результат для CSM: {case['result']}\n\n"
        "Сформируй ответ по-русски, без технических слов. "
        "Структура: кратко, как показать в демо, что получит CSM, следующий шаг. "
        "Не проси пользователя задавать вопрос."
    )
    async with SessionLocal() as session:
        response = await ask_agent(session, AIAskRequest(question=question, channel="telegram"))
    set_pending_ai_context(callback.from_user.id, _case_context(case))
    await callback.message.answer(
        f"{compact_ai_answer(response.answer)}\n\n"
        "Можно задать уточнение по этому кейсу текстом или голосовым сообщением 🎙",
        reply_markup=back_home_keyboard(f"case:{case_key}"),
    )


def _case_text(case: dict[str, str]) -> str:
    return (
        f"{case['title']}\n\n"
        f"Ситуация: {case['situation']}\n\n"
        f"Что делает бот: {case['bot']}\n\n"
        f"Результат для CSM: {case['result']}\n\n"
        "Можно спросить AI по этому кейсу, а потом отправить уточнение текстом или голосом 🎙"
    )


def _case_context(case: dict[str, str]) -> str:
    return (
        f"Пользователь задаёт уточняющий вопрос по кейсу CSM Pulse: {case['title']}.\n"
        f"Ситуация: {case['situation']}\n"
        f"Что делает бот: {case['bot']}\n"
        f"Результат для CSM: {case['result']}\n"
        "Ответь по-русски, коротко и практично."
    )
