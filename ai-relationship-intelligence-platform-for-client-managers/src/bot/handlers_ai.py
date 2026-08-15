from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from typing import Optional

from src.ai.agent_service import ask_agent
from src.ai.voice_service import VoiceTooLongError, VoiceTranscriptionError, transcribe_telegram_voice
from src.bot.formatters import compact_ai_answer
from src.bot.keyboards import ai_keyboard, ask_ai_home_keyboard, back_home_keyboard
from src.db import SessionLocal
from src.schemas import AIAskRequest


router = Router()
WAITING_AI_USERS: set[int] = set()
AI_CONTEXT_BY_USER: dict[int, str] = {}

QUICK_QUESTIONS = {
    "attention": "Что требует внимания сегодня?",
    "tasks": "Какие задачи сейчас горят?",
    "calendar": "К каким встречам сегодня подготовиться?",
    "risks": "Какие клиенты в риске и что делать?",
}


@router.message(Command("ask"))
async def ask_command(message: Message) -> None:
    question = message.text.replace("/ask", "", 1).strip()
    if not question:
        await _ask_prompt(message)
        return
    await _answer_question(message, question)


@router.callback_query(lambda c: c.data == "ask_ai")
async def ask_ai(callback: CallbackQuery) -> None:
    await callback.answer()
    await set_ai_mode(callback.message, callback.from_user.id)


@router.callback_query(lambda c: c.data and c.data.startswith("ai_quick:"))
async def ai_quick(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    question = QUICK_QUESTIONS.get(key, "Что требует внимания?")
    await callback.answer("Спрашиваю AI...")
    await _answer_question(callback.message, question)


@router.message(F.voice)
@router.message(F.audio)
async def voice(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id if message.from_user else 0
    in_ai_mode = bool(user_id and user_id in WAITING_AI_USERS)
    await message.answer("🎙 Распознаю голосовое сообщение...")
    try:
        question = await transcribe_telegram_voice(bot, message)
    except VoiceTooLongError:
        await message.answer(
            "Голосовое сообщение слишком длинное. Запишите короче или напишите текстом.",
            reply_markup=back_home_keyboard(),
        )
        return
    except VoiceTranscriptionError:
        await message.answer(
            "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.",
            reply_markup=back_home_keyboard(),
        )
        return

    if not question.strip():
        await message.answer(
            "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.",
            reply_markup=back_home_keyboard(),
        )
        return

    await message.answer(f"🎙 Распознал: {question}")
    if not in_ai_mode:
        await message.answer(
            "🎙 Я распознал голосовое сообщение. Чтобы задать вопрос голосом, нажмите 🤖 Спросить AI.",
            reply_markup=ask_ai_home_keyboard(),
        )
        return

    WAITING_AI_USERS.discard(user_id)
    context = AI_CONTEXT_BY_USER.pop(user_id, "")
    await _answer_question(message, question, context=context)


@router.message(F.text, lambda message: bool(message.from_user and message.from_user.id in WAITING_AI_USERS))
async def ai_text_question(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    WAITING_AI_USERS.discard(user_id)
    context = AI_CONTEXT_BY_USER.pop(user_id, "")
    await _answer_question(message, message.text, context=context)


async def set_ai_mode(message: Message, user_id: int, context: str = "") -> None:
    if context:
        AI_CONTEXT_BY_USER[user_id] = context
    else:
        AI_CONTEXT_BY_USER.pop(user_id, None)
    await _ask_prompt(message, user_id=user_id)


def set_pending_ai_context(user_id: int, context: str = "") -> None:
    WAITING_AI_USERS.add(user_id)
    if context:
        AI_CONTEXT_BY_USER[user_id] = context
    else:
        AI_CONTEXT_BY_USER.pop(user_id, None)


async def _ask_prompt(message: Message, user_id: Optional[int] = None) -> None:
    if user_id is None and message.from_user:
        user_id = message.from_user.id
    if user_id:
        WAITING_AI_USERS.add(user_id)
    await message.answer(
        "Напишите вопрос по клиентам, задачам, рискам или встречам.\n"
        "Можно отправить текст или записать голосовое сообщение 🎙\n\n"
        "Например: «Что делать с Ритейл Плюс?»",
        reply_markup=ai_keyboard(),
    )


async def _answer_question(message: Message, question: str, context: str = "") -> None:
    if context:
        question = f"{context}\n\nВопрос пользователя: {question}"
    async with SessionLocal() as session:
        response = await ask_agent(session, AIAskRequest(question=question, channel="telegram"))
    await message.answer(compact_ai_answer(response.answer), reply_markup=back_home_keyboard())
