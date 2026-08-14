from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.handlers.avatar_selection import show_avatar
from src.bot.handlers.workflow import _show_review, show_final_confirmation
from src.bot.keyboards.common import (
    back_main,
    error_video_keyboard,
    generation_status_keyboard,
    history_item_keyboard,
    main_menu,
    ready_video_keyboard,
    source_choice,
)
from src.bot.states.workflow import Workflow
from src.database.models import VideoStatus
from src.database.repositories import get_user_draft, list_videos, update_draft
from src.services.avatar_catalog import active_avatars
from src.services.heygen import HeyGenClient

router = Router()

STATUS_NAMES = {
    VideoStatus.DRAFT.value: "Draft",
    VideoStatus.AWAITING_CONFIRMATION.value: "Awaiting confirmation",
    VideoStatus.GENERATING.value: "Generating",
    VideoStatus.READY.value: "Ready",
    VideoStatus.ERROR.value: "Error",
}


def _video_type_name(video_type: str) -> str:
    return {"greeting": "Greeting", "meeting": "Team update", "news": "News"}.get(video_type, video_type)


def _card_text(draft) -> str:
    text = (draft.normalized_text or draft.current_text or draft.source_text or "")
    fragment = text[:120] + ("…" if len(text) > 120 else "")
    return (
        f"{draft.created_at:%d.%m.%Y %H:%M} · {_video_type_name(draft.video_type)}\n"
        f"Style: {draft.avatar_name or 'not selected'}\n"
        f"Status: {STATUS_NAMES.get(draft.status, draft.status)}"
        + (f"\nScript: {fragment}" if fragment else "")
    )


async def show_history(message: Message, user_id: int, index: int = 0, edit: bool = False) -> None:
    rows = list_videos(user_id)
    if not rows:
        await message.answer("You do not have any saved video requests yet.", reply_markup=main_menu())
        return
    index %= len(rows)
    draft = rows[index]
    text = f"My videos · {index + 1} of {len(rows)}\n\n{_card_text(draft)}"
    keyboard = history_item_keyboard(draft.id, index, len(rows))
    if edit:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=keyboard)


def _infer_step(draft) -> str:
    if draft.normalized_text:
        return "final_confirmation"
    if draft.current_text:
        return "review_text"
    if not draft.avatar_key:
        return "selecting_avatar"
    if draft.video_type == "greeting":
        data = draft.greeting_data or {}
        if not data.get("recipient"):
            return "greeting_recipient"
        if not data.get("occasion"):
            return "greeting_occasion"
        return "greeting_details"
    return "source_choice"


async def _resume_draft(message: Message, state: FSMContext, draft) -> None:
    step = draft.current_step or _infer_step(draft)
    greeting = dict(draft.greeting_data or {})
    await state.clear()
    await state.update_data(
        draft_id=draft.id,
        recipient=greeting.get("recipient", ""),
        occasion=greeting.get("occasion", ""),
    )

    if step == "selecting_avatar":
        await state.set_state(Workflow.selecting_avatar)
        avatars = active_avatars()
        avatar_index = next((index for index, avatar in enumerate(avatars) if avatar.id == draft.avatar_key), 0)
        await show_avatar(message, state, draft.id, avatar_index)
    elif step == "greeting_recipient":
        await state.set_state(Workflow.greeting_recipient)
        await message.answer("Who is the greeting for? You can enter a name, role or team name.", reply_markup=back_main("nav:avatar_back"))
    elif step == "greeting_occasion":
        await state.set_state(Workflow.greeting_occasion)
        await message.answer("What is the occasion?", reply_markup=back_main("nav:greeting_recipient"))
    elif step == "greeting_details":
        await state.set_state(Workflow.greeting_details)
        await message.answer("Add a role, team, achievements, preferred tone or other details. Send 'Skip' to continue without them.", reply_markup=back_main("nav:greeting_occasion"))
    elif step == "source_text":
        await state.set_state(Workflow.source_text)
        await message.answer("Send the script you want the avatar to deliver.", reply_markup=back_main("nav:source"))
    elif step == "review_text" and draft.current_text:
        await state.set_state(Workflow.review_text)
        await _show_review(message, draft.id)
    elif step == "final_confirmation" and draft.normalized_text:
        await show_final_confirmation(message, state, draft)
    else:
        await state.set_state(Workflow.source_choice)
        update_draft(draft.id, current_step="source_choice")
        await message.answer("How would you like to provide the script?", reply_markup=source_choice())


async def _show_generating(message: Message, draft) -> None:
    await message.answer(
        "The video is being generated. Its status will continue to update automatically.",
        reply_markup=generation_status_keyboard(draft.id),
    )


async def _show_ready(message: Message, draft) -> None:
    await message.answer(
        "The video is ready. You can retrieve it again or open the link.",
        reply_markup=ready_video_keyboard(draft.id, bool(draft.video_url)),
    )


async def _show_error(message: Message, state: FSMContext, draft) -> None:
    reason = draft.error_message or "The generation service did not provide a reason."
    await state.update_data(draft_id=draft.id)
    await state.set_state(Workflow.final_confirmation)
    await message.answer(
        f"The video could not be generated or retrieved.\n\nReason: {reason}\n\n"
        "Return to final confirmation, change the script or avatar, and try again.",
        reply_markup=error_video_keyboard(draft.id),
    )


async def _open_draft(message: Message, state: FSMContext, draft) -> None:
    if draft.status == VideoStatus.DRAFT.value:
        await _resume_draft(message, state, draft)
    elif draft.status == VideoStatus.AWAITING_CONFIRMATION.value:
        await state.clear()
        await show_final_confirmation(message, state, draft)
    elif draft.status == VideoStatus.GENERATING.value:
        await state.clear()
        await _show_generating(message, draft)
    elif draft.status == VideoStatus.READY.value:
        await state.clear()
        await _show_ready(message, draft)
    elif draft.status == VideoStatus.ERROR.value:
        await state.clear()
        await _show_error(message, state, draft)


@router.callback_query(lambda callback: callback.data == "menu:history")
async def history(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    await state.clear()
    await show_history(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:open:"))
async def open_history_draft(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    draft_id = int(callback.data.rsplit(":", 1)[1])
    draft = get_user_draft(draft_id, callback.from_user.id)
    if draft is None:
        await callback.answer("This video request is unavailable", show_alert=True)
        return
    await _open_draft(callback.message, state, draft)
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:page:"))
async def history_page(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    index = int(callback.data.rsplit(":", 1)[1])
    await show_history(callback.message, callback.from_user.id, index=index, edit=True)
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:refresh:"))
async def refresh_generation(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    draft_id = int(callback.data.rsplit(":", 1)[1])
    draft = get_user_draft(draft_id, callback.from_user.id)
    if draft is None or draft.status != VideoStatus.GENERATING.value or not draft.heygen_video_id:
        await callback.answer("This video request is no longer generating", show_alert=True)
        return
    try:
        status, url, error = await asyncio.to_thread(HeyGenClient().status, draft.heygen_video_id)
    except Exception:
        await callback.answer("The status could not be refreshed. Try again later.", show_alert=True)
        return
    if status == "ready":
        draft = update_draft(draft.id, status=VideoStatus.READY.value, current_step="ready", video_url=url)
        await _show_ready(callback.message, draft)
    elif status == "error":
        draft = update_draft(draft.id, status=VideoStatus.ERROR.value, current_step="final_confirmation", error_message=error)
        await _show_error(callback.message, state, draft)
    else:
        await callback.answer("The video is still being generated")
        return
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:get_video:"))
async def get_ready_video(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    draft_id = int(callback.data.rsplit(":", 1)[1])
    draft = get_user_draft(draft_id, callback.from_user.id)
    if draft is None or draft.status != VideoStatus.READY.value or not draft.video_url:
        await callback.answer("The video or link is not available yet", show_alert=True)
        return
    try:
        await callback.message.answer_video(draft.video_url, caption="Your finished video")
    except Exception:
        await callback.message.answer(f"Finished video: {draft.video_url}")
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:link:"))
async def get_ready_link(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    draft_id = int(callback.data.rsplit(":", 1)[1])
    draft = get_user_draft(draft_id, callback.from_user.id)
    if draft is None or not draft.video_url:
        await callback.answer("The link is not available yet", show_alert=True)
        return
    await callback.message.answer(f"Finished video link:\n{draft.video_url}")
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("history:resume_error:"))
async def resume_error_draft(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    draft_id = int(callback.data.rsplit(":", 1)[1])
    draft = get_user_draft(draft_id, callback.from_user.id)
    if draft is None or draft.status != VideoStatus.ERROR.value:
        await callback.answer("This error is no longer current", show_alert=True)
        return
    await show_final_confirmation(callback.message, state, draft)
    await callback.answer()
