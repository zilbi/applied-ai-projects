from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.bot.keyboards.common import avatar_keyboard, back_main
from src.bot.states.workflow import Workflow
from src.database.repositories import get_draft, update_draft
from src.services.avatar_catalog import Avatar, active_avatars, preview_path

router = Router()

AVATAR_SELECTION_INSTRUCTION = (
    "Choose an avatar style for your video.\n\n"
    "Watch the preview for the current option. Use Previous and Next to browse "
    "other styles. When you are ready, select this avatar."
)


def avatar_card_text(avatar: Avatar) -> str:
    return f"{avatar.style_name} style\n\n{avatar.description}"


async def _safe_delete(message: Message, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await message.bot.delete_message(message.chat.id, message_id)
    except Exception:
        pass


async def _safe_delete_current_card(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass


async def _show_preview(message: Message, avatar: Avatar) -> int | None:
    if avatar.demo_video.startswith(("http://", "https://")):
        sent = await message.answer_video(avatar.demo_video)
    elif (path := preview_path(avatar)) and path.is_file():
        sent = await message.answer_video(FSInputFile(path))
    else:
        return None
    return getattr(sent, "message_id", None)


async def show_avatar(
    callback: CallbackQuery | Message,
    state: FSMContext,
    draft_id: int,
    index: int,
    *,
    show_instruction: bool = True,
) -> None:
    avatars = active_avatars()
    message = getattr(callback, "message", None) or callback
    if not avatars or not hasattr(message, "answer"):
        if hasattr(callback, "answer"):
            await callback.answer("The avatar catalog is empty", show_alert=True)
        return

    index %= len(avatars)
    avatar = avatars[index]
    data = await state.get_data()
    if show_instruction:
        await message.answer(AVATAR_SELECTION_INSTRUCTION)
    else:
        await _safe_delete(message, data.get("avatar_preview_message_id"))
        if isinstance(callback, CallbackQuery):
            await _safe_delete_current_card(callback)

    preview_message_id = await _show_preview(message, avatar)
    card = await message.answer(
        avatar_card_text(avatar),
        reply_markup=avatar_keyboard(draft_id, index, len(avatars)),
    )
    await state.update_data(
        draft_id=draft_id,
        avatar_index=index,
        avatar_preview_message_id=preview_message_id,
        avatar_card_message_id=getattr(card, "message_id", None),
    )


def _is_current_avatar(data: dict, draft_id: int, index: int, total: int) -> bool:
    return data.get("draft_id") == draft_id and data.get("avatar_index") == index % total


@router.callback_query(lambda c: c.data and c.data.startswith("avatar:show:"))
async def avatar_show(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    _, _, raw_draft_id, raw_current_index, raw_target_index = parts
    draft_id, current_index, target_index = int(raw_draft_id), int(raw_current_index), int(raw_target_index)
    avatars = active_avatars()
    data = await state.get_data()
    if (
        not avatars
        or not _is_current_avatar(data, draft_id, current_index, len(avatars))
        or await state.get_state() != Workflow.selecting_avatar.state
    ):
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    await show_avatar(callback, state, draft_id, target_index, show_instruction=False)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("avatar:choose:"))
async def avatar_choose(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, raw_draft_id, raw_index = callback.data.split(":")
    draft_id, index = int(raw_draft_id), int(raw_index)
    avatars = active_avatars()
    data = await state.get_data()
    if (
        not avatars
        or not _is_current_avatar(data, draft_id, index, len(avatars))
        or await state.get_state() != Workflow.selecting_avatar.state
    ):
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return

    avatar = avatars[index % len(avatars)]
    next_step = "greeting_recipient" if get_draft(draft_id).video_type == "greeting" else "source_choice"
    update_draft(draft_id, avatar_key=avatar.id, avatar_name=avatar.name, current_step=next_step)
    draft = get_draft(draft_id, callback.from_user.id if callback.from_user else None)
    if not draft or not callback.message:
        return

    await _safe_delete(callback.message, data.get("avatar_preview_message_id"))
    confirmation = f"Avatar selected:\n\n{avatar.style_name} style\n\nContinue to the next step."
    try:
        await callback.message.edit_text(confirmation)
    except Exception:
        await callback.message.answer(confirmation)
    await state.update_data(avatar_preview_message_id=None, avatar_card_message_id=None)

    if draft.video_type == "greeting":
        await state.set_state(Workflow.greeting_recipient)
        await callback.message.answer(
            "Who is the greeting for? You can enter a name, role or team name.",
            reply_markup=back_main("nav:avatar_back"),
        )
    else:
        await state.set_state(Workflow.source_choice)
        from src.bot.keyboards.common import source_choice
        await callback.message.answer("How would you like to provide the script?", reply_markup=source_choice())
    await callback.answer("Avatar selected")
