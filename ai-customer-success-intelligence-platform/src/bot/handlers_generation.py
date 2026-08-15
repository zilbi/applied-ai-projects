from datetime import datetime
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.ai.report_generator import generate_csv, generate_risk_report
from src.bot.keyboards import back_home_keyboard, generation_confirm_keyboard, generation_keyboard
from src.db import SessionLocal
from src.schemas import GenerateCSVRequest, GenerateReportRequest


router = Router()
OUTPUTS = Path("outputs")

PREVIEWS = {
    "report": "📄 Отчёт по рискам\n\nБудет создан PDF-файл с кратким выводом, открытыми рисками и действиями CSM.",
    "email": "✉️ Письмо клиенту\n\nБудет создан короткий текст письма по клиенту в зоне риска.",
    "hypothesis": "🧪 Гипотеза удержания\n\nБудет создана гипотеза: проблема, проверка, следующий шаг.",
    "csv": "📊 CSV с метриками\n\nБудет создан CSV-файл с демо-метриками NPS для отправки в чат.",
}


@router.message(Command("generate"))
async def generation_command(message: Message) -> None:
    await message.answer("⚙️ Генерация\n\nВыберите, что подготовить:", reply_markup=generation_keyboard())


@router.callback_query(lambda c: c.data == "generation")
async def generation_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("⚙️ Генерация\n\nВыберите, что подготовить:", reply_markup=generation_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("gen_preview:"))
async def generation_preview(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]
    await callback.answer()
    await callback.message.answer(PREVIEWS.get(kind, "Подготовить артефакт?"), reply_markup=generation_confirm_keyboard(kind))


@router.callback_query(lambda c: c.data and c.data.startswith("gen_cancel:"))
async def generation_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    await callback.message.answer("Ок, ничего не сохраняю и не отправляю.", reply_markup=back_home_keyboard("generation"))


@router.callback_query(lambda c: c.data and c.data.startswith("gen_confirm:"))
async def generation_confirm(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]
    await callback.answer("Готовлю...")
    if kind == "csv":
        async with SessionLocal() as session:
            result = await generate_csv(session, GenerateCSVRequest(rows=100))
        await _send_file(callback, result["file_path"], "CSV с метриками готов")
    elif kind == "report":
        async with SessionLocal() as session:
            result = await generate_risk_report(session, GenerateReportRequest())
        await _send_file(callback, result["file_path"], "Отчёт по рискам готов")
    elif kind == "email":
        content = _email_template()
        path = _write_text_file("client_email", content)
        await callback.message.answer(content)
        await _send_file(callback, str(path), "Письмо клиенту готово")
    elif kind == "hypothesis":
        content = _hypothesis_template()
        path = _write_text_file("retention_hypothesis", content)
        await _send_file(callback, str(path), "Гипотеза удержания готова")
    else:
        await callback.message.answer("Этот тип генерации пока не поддержан в MVP.", reply_markup=back_home_keyboard("generation"))


async def _send_file(callback: CallbackQuery, file_path: str, caption: str) -> None:
    path = Path(file_path)
    if not path.exists():
        await callback.message.answer(f"{caption}, но файл не найден.", reply_markup=back_home_keyboard("generation"))
        return
    await callback.message.answer_document(FSInputFile(path), caption=caption)
    await callback.message.answer("Готово. Что подготовить дальше?", reply_markup=back_home_keyboard("generation"))


def _write_text_file(prefix: str, content: str) -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def _email_template() -> str:
    return (
        "Тема: Короткая синхронизация по текущему статусу\n\n"
        "Здравствуйте!\n\n"
        "Предлагаю коротко обсудить текущий статус: видим несколько сигналов, которые лучше разобрать заранее.\n"
        "Хочу сверить ожидания, договориться о следующем шаге и зафиксировать контрольную дату.\n\n"
        "Можем созвониться на 20 минут сегодня или завтра?"
    )


def _hypothesis_template() -> str:
    return (
        "Гипотеза удержания\n\n"
        "Проблема: у клиента снижается вовлечённость или растёт риск оттока.\n\n"
        "Гипотеза: если согласовать 14-дневный success-plan с одним измеримым KPI, клиент быстрее увидит ценность.\n\n"
        "Проверка:\n"
        "1. Созвон с decision maker.\n"
        "2. Выбор одного бизнес-сценария.\n"
        "3. Контроль активности, NPS и следующего платежа через 14 дней.\n\n"
        "Следующий шаг: создать задачу CSM на контакт с клиентом."
    )
