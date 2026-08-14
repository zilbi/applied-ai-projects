from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.handlers.avatar_selection import show_avatar
from src.bot.keyboards.common import back_main, final_keyboard, main_menu, review_keyboard, source_choice, video_types, voice_confirmation_keyboard
from src.bot.states.workflow import Workflow
from src.core.config import ROOT, settings
from src.database.models import VideoStatus
from src.database.repositories import append_revision, create_draft, get_draft, update_draft
from src.services.gigachat import GigaChatError, complete
from src.services.heygen import HeyGenClient, HeyGenError
from src.services.speech_to_text import SpeechToTextError, transcribe
from src.services.telegram_voice import TelegramVoiceError, download_as_wav
from src.services.text_normalizer import normalize
from src.services.avatar_catalog import get_avatar, read_motion_prompt

router = Router()


def _template(name: str, **values: str) -> str:
    return (ROOT / "src" / "prompts" / name).read_text(encoding="utf-8").format(**values)


async def _show_transcript_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = (data.get("corrected_transcript") or data.get("recognized_transcript") or "").strip()
    target = data.get("voice_target")
    if not text or not target:
        await message.answer("The recognized text is no longer available. Record the message again.")
        return
    heading = "I recognized your requested changes as:" if target == "revision" else "Recognized text:"
    await state.set_state(Workflow.confirming_transcript)
    await message.answer(
        f"{heading}\n\n{text}\n\nConfirm that this is what you said:",
        reply_markup=voice_confirmation_keyboard(target),
    )


async def _ask_for_voice(message: Message, state: FSMContext, target: str, prompt: str) -> None:
    await state.update_data(
        voice_target=target,
        voice_file_id=None,
        voice_message_id=None,
        recognized_transcript=None,
        corrected_transcript=None,
    )
    await state.set_state(Workflow.waiting_voice)
    await message.answer(prompt, reply_markup=back_main("voice:back"))


async def _capture_voice(message: Message, state: FSMContext) -> None:
    path: Path | None = None
    try:
        path = await download_as_wav(message.bot, message)
        transcript = await asyncio.to_thread(transcribe, path)
    except (TelegramVoiceError, SpeechToTextError) as exc:
        await message.answer(f"The message could not be transcribed: {exc}")
        return
    finally:
        if path is not None:
            path.unlink(missing_ok=True)

    source = message.voice or message.audio
    await state.update_data(
        voice_file_id=source.file_id if source else None,
        voice_message_id=message.message_id,
        recognized_transcript=transcript,
        corrected_transcript=None,
    )
    await _show_transcript_confirmation(message, state)


async def _generate_greeting(message: Message, state: FSMContext, details: str) -> None:
    data = await state.get_data()
    draft_id = data["draft_id"]
    await message.answer("Preparing the greeting script…")
    try:
        text = await asyncio.to_thread(
            complete,
            _template(
                "congratulations.txt",
                recipient=data["recipient"],
                occasion=data["occasion"],
                details=details,
            ),
        )
    except GigaChatError:
        await message.answer("The script could not be prepared. Check the GigaChat configuration and try again.")
        return
    update_draft(
        draft_id,
        source_text=text,
        current_text=text,
        greeting_data={"recipient": data["recipient"], "occasion": data["occasion"], "details": details},
    )
    await state.set_state(Workflow.review_text)
    await _show_review(message, draft_id)


async def _use_confirmed_transcript(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = (data.get("corrected_transcript") or data.get("recognized_transcript") or "").strip()
    target = data.get("voice_target")
    await state.update_data(
        voice_file_id=None,
        voice_message_id=None,
        recognized_transcript=None,
        corrected_transcript=None,
        voice_target=None,
    )
    if target == "source":
        await _process_source(message, state, text)
    elif target == "revision":
        await _apply_edit(message, state, text)
    elif target == "greeting_details":
        await _generate_greeting(message, state, text)


async def _current_draft_callback(
    callback: CallbackQuery,
    state: FSMContext,
    draft_id: int,
    *allowed_states: str,
) -> bool:
    """Reject callbacks from an earlier inline keyboard or another draft."""
    data = await state.get_data()
    current_state = await state.get_state()
    if data.get("draft_id") != draft_id or (allowed_states and current_state not in allowed_states):
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return False
    if callback.from_user and get_draft(draft_id, callback.from_user.id) is None:
        await callback.answer("The draft is unavailable", show_alert=True)
        return False
    return True


async def _show_review(message: Message, draft_id: int) -> None:
    draft = get_draft(draft_id)
    if not draft: return
    update_draft(draft_id, current_step="review_text")
    text = draft.current_text or ""
    await message.answer(f"Prepared script:\n\n{text}", reply_markup=review_keyboard(draft_id, draft.video_type != "greeting"))


async def show_final_confirmation(message: Message, state: FSMContext, draft) -> None:
    if not draft.normalized_text:
        await message.answer("This video request has no prepared final script.")
        return
    await state.update_data(draft_id=draft.id)
    await state.set_state(Workflow.final_confirmation)
    update_draft(draft.id, current_step="final_confirmation")
    seconds = max(1, round(len(draft.normalized_text.split()) / 2.3))
    avatar = draft.avatar_name or "not selected"
    card = (
        "Final confirmation.\n\n"
        f"Video type: {draft.video_type}\n"
        f"Avatar: {avatar}\n"
        f"Estimated duration: {seconds} seconds\n\n"
        f"Final script:\n{draft.normalized_text}"
    )
    await message.answer(card, reply_markup=final_keyboard(draft.id))


async def _normalization_card(message: Message, draft_id: int, state: FSMContext) -> None:
    draft = get_draft(draft_id)
    if not draft or not draft.current_text: return
    await message.answer("Checking the script for spoken delivery…")
    result = normalize(draft.current_text)
    update_draft(draft_id, normalized_text=result.normalized_text, normalization_notes=result.issues, status=VideoStatus.AWAITING_CONFIRMATION.value, current_step="final_confirmation")
    avatar = draft.avatar_name or "not selected"
    seconds = max(1, round(len(result.normalized_text.split()) / 2.3))
    warnings = "\n\nNeeds clarification: " + "; ".join(result.warnings) if result.warnings else ""
    fixes = "\nChanges: " + "; ".join(result.issues) if result.issues else ""
    await state.set_state(Workflow.final_confirmation)
    card = f"Preparing the final version.\n\nVideo type: {draft.video_type}\nAvatar: {avatar}\nEstimated duration: {seconds} seconds\n\nFinal script:\n{result.normalized_text}{fixes}{warnings}"
    if result.warnings:
        update_draft(draft_id, status=VideoStatus.DRAFT.value)
        await message.answer(card + "\n\nAn abbreviation was not recognized. Submit a change with its full expansion.", reply_markup=review_keyboard(draft_id, draft.video_type != "greeting"))
    else:
        await message.answer(card, reply_markup=final_keyboard(draft_id))


@router.callback_query(lambda c: c.data == "menu:create")
async def menu_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Workflow.choosing_type)
    if callback.message: await callback.message.answer("Choose a video type.", reply_markup=video_types())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("type:"))
async def choose_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user: return
    if await state.get_state() != Workflow.choosing_type.state:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    kind = callback.data.split(":", 1)[1]
    draft = create_draft(callback.from_user.id, kind, current_step="selecting_avatar")
    await state.set_state(Workflow.selecting_avatar)
    await show_avatar(callback, state, draft.id, 0)
    await callback.answer()


@router.callback_query(lambda c: c.data == "source:text")
async def source_text(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != Workflow.source_choice.state:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    await state.set_state(Workflow.source_text)
    data = await state.get_data()
    if data.get("draft_id"):
        update_draft(data["draft_id"], current_step="source_text")
    if callback.message: await callback.message.answer("Send the script you want the avatar to deliver.", reply_markup=back_main("nav:source"))
    await callback.answer()


@router.callback_query(lambda c: c.data == "source:voice")
async def source_voice(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != Workflow.source_choice.state:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    if callback.message:
        data = await state.get_data()
        if data.get("draft_id"):
            update_draft(data["draft_id"], current_step="source_choice")
        await _ask_for_voice(callback.message, state, "source", "Record a voice message with the video script.")
    await callback.answer()


@router.message(Workflow.greeting_recipient, F.text)
async def greeting_recipient(message: Message, state: FSMContext) -> None:
    recipient = message.text.strip()
    data = await state.get_data()
    await state.update_data(recipient=recipient); await state.set_state(Workflow.greeting_occasion)
    if data.get("draft_id"):
        draft = get_draft(data["draft_id"])
        greeting_data = dict(draft.greeting_data or {}) if draft else {}
        greeting_data["recipient"] = recipient
        update_draft(data["draft_id"], greeting_data=greeting_data, current_step="greeting_occasion")
    await message.answer("What is the occasion?", reply_markup=back_main("nav:greeting_recipient"))


@router.message(Workflow.greeting_occasion, F.text)
async def greeting_occasion(message: Message, state: FSMContext) -> None:
    occasion = message.text.strip()
    data = await state.get_data()
    await state.update_data(occasion=occasion); await state.set_state(Workflow.greeting_details)
    if data.get("draft_id"):
        draft = get_draft(data["draft_id"])
        greeting_data = dict(draft.greeting_data or {}) if draft else {}
        greeting_data["occasion"] = occasion
        update_draft(data["draft_id"], greeting_data=greeting_data, current_step="greeting_details")
    await message.answer("Add a role, team, achievements, preferred tone or other details. Send 'Skip' to continue without them.", reply_markup=back_main("nav:greeting_occasion"))


@router.message(Workflow.greeting_details, F.text)
async def greeting_details(message: Message, state: FSMContext) -> None:
    details = "" if message.text.strip().lower() == "skip" else message.text.strip()
    await _generate_greeting(message, state, details)


@router.message(Workflow.greeting_details, F.voice | F.audio)
async def greeting_details_voice(message: Message, state: FSMContext) -> None:
    await state.update_data(
        voice_target="greeting_details",
        voice_file_id=None,
        voice_message_id=None,
        recognized_transcript=None,
        corrected_transcript=None,
    )
    await _capture_voice(message, state)


async def _process_source(message: Message, state: FSMContext, text: str) -> None:
    data = await state.get_data(); draft_id = data["draft_id"]
    if not text.strip(): await message.answer("The script is empty. Try again."); return
    if len(text) > settings.max_text_length: await message.answer(f"The script exceeds {settings.max_text_length} characters. Please shorten it."); return
    await message.answer("Checking and preparing the script…")
    try:
        prepared = await asyncio.to_thread(complete, _template("text_normalization.txt", text=text.strip()))
    except GigaChatError:
        await message.answer("The script could not be prepared. Try again later."); return
    update_draft(draft_id, source_text=text.strip(), current_text=prepared, current_step="review_text")
    await state.set_state(Workflow.review_text); await _show_review(message, draft_id)


@router.message(Workflow.source_text, F.text)
async def source_text_message(message: Message, state: FSMContext) -> None:
    await _process_source(message, state, message.text)


@router.message(Workflow.source_text, F.voice | F.audio)
async def source_voice_message(message: Message, state: FSMContext) -> None:
    await state.update_data(
        voice_target="source",
        voice_file_id=None,
        voice_message_id=None,
        recognized_transcript=None,
        corrected_transcript=None,
    )
    await _capture_voice(message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("text:edit:"))
async def edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state, Workflow.final_confirmation.state): return
    await state.set_state(Workflow.text_correction)
    if callback.message: await callback.message.answer("Describe what you want to change.", reply_markup=back_main("nav:review_back"))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("text:voice:"))
async def voice_edit(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state, Workflow.final_confirmation.state): return
    if callback.message:
        await _ask_for_voice(callback.message, state, "revision", "Record your requested script changes as a voice message.")
    await callback.answer()


async def _apply_edit(message: Message, state: FSMContext, instruction: str) -> None:
    draft_id = (await state.get_data())["draft_id"]; draft = get_draft(draft_id)
    if not draft or not draft.current_text: await message.answer("The draft is no longer available."); return
    await message.answer("Applying the requested changes…")
    try: text = await asyncio.to_thread(complete, _template("text_editing.txt", text=draft.current_text, instruction=instruction))
    except GigaChatError: await message.answer("The changes could not be applied. Try again later."); return
    append_revision(draft_id, instruction, text); await state.set_state(Workflow.review_text); await _show_review(message, draft_id)


@router.message(Workflow.text_correction, F.text)
async def text_correction(message: Message, state: FSMContext) -> None:
    await _apply_edit(message, state, message.text)


@router.message(Workflow.waiting_voice, F.voice | F.audio)
@router.message(Workflow.rerecording_voice, F.voice | F.audio)
async def voice_message(message: Message, state: FSMContext) -> None:
    await _capture_voice(message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("voice:"))
async def voice_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    data = await state.get_data()
    target = data.get("voice_target")
    if not callback.message or not target:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    if action in {"confirm", "retry", "edit", "cancel"} and current_state != Workflow.confirming_transcript.state:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    if action == "back" and current_state not in {
        Workflow.waiting_voice.state,
        Workflow.rerecording_voice.state,
        Workflow.confirming_transcript.state,
        Workflow.correcting_transcript.state,
    }:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    if action == "confirm":
        await _use_confirmed_transcript(callback.message, state)
    elif action == "retry":
        await state.update_data(voice_file_id=None, voice_message_id=None, recognized_transcript=None, corrected_transcript=None)
        await state.set_state(Workflow.rerecording_voice)
        await callback.message.answer("The previous transcription will be discarded. Record a new voice message.", reply_markup=back_main("voice:back"))
    elif action == "edit":
        await state.set_state(Workflow.correcting_transcript)
        await callback.message.answer("Send the complete corrected version of the recognized text.", reply_markup=back_main("voice:back"))
    elif action == "cancel" and target == "revision":
        draft_id = data.get("draft_id")
        await state.set_state(Workflow.review_text)
        if draft_id:
            await _show_review(callback.message, draft_id)
    elif action == "back":
        if current_state == Workflow.correcting_transcript.state:
            await _show_transcript_confirmation(callback.message, state)
        elif target == "source":
            await state.set_state(Workflow.source_choice)
            await callback.message.answer("How would you like to provide the script?", reply_markup=source_choice())
        elif target == "revision":
            draft_id = data.get("draft_id")
            await state.set_state(Workflow.review_text)
            if draft_id:
                await _show_review(callback.message, draft_id)
        elif target == "greeting_details":
            await state.set_state(Workflow.greeting_details)
            await callback.message.answer("Add a role, team, achievements, preferred tone or other details. Send 'Skip' to continue without them.", reply_markup=back_main("nav:greeting_occasion"))
    else:
        await callback.answer("This button belongs to an earlier step", show_alert=True)
        return
    await callback.answer()


@router.message(Workflow.correcting_transcript, F.text)
async def corrected_transcript(message: Message, state: FSMContext) -> None:
    if not message.text.strip():
        await message.answer("The text is empty. Send the corrected version again.")
        return
    await state.update_data(corrected_transcript=message.text.strip())
    await _show_transcript_confirmation(message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("text:regenerate:"))
async def regenerate(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state): return
    draft = get_draft(draft_id)
    if not draft or not callback.message: return
    if draft.video_type != "greeting": await callback.answer("Edit the script manually for this video type", show_alert=True); return
    info = draft.greeting_data
    try: text = await asyncio.to_thread(complete, _template("congratulations.txt", recipient=info["recipient"], occasion=info["occasion"], details=info.get("details", "")))
    except (GigaChatError, KeyError): await callback.answer("A new version could not be generated", show_alert=True); return
    append_revision(draft_id, "Generate again", text); await _show_review(callback.message, draft_id); await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("text:original:"))
async def original(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state): return
    draft = get_draft(draft_id)
    if not draft or not draft.source_text or not callback.message: return
    append_revision(draft_id, "Restore original", draft.source_text); await _show_review(callback.message, draft_id); await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("text:confirm:"))
async def confirm_text(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state): return
    if callback.message: await _normalization_card(callback.message, draft_id, state)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("avatar:edit:"))
async def edit_avatar(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.review_text.state, Workflow.final_confirmation.state): return
    update_draft(draft_id, current_step="selecting_avatar")
    await state.set_state(Workflow.selecting_avatar); await show_avatar(callback, state, draft_id, 0); await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("video:generate:"))
async def generate(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.rsplit(":", 1)[1])
    if not await _current_draft_callback(callback, state, draft_id, Workflow.final_confirmation.state): return
    draft = get_draft(draft_id, callback.from_user.id if callback.from_user else None)
    if not draft or not callback.message: return
    if draft.status == VideoStatus.GENERATING.value:
        await callback.answer("The video is already being generated", show_alert=True); return
    if draft.status not in {VideoStatus.AWAITING_CONFIRMATION.value, VideoStatus.ERROR.value} or not draft.normalized_text:
        await callback.answer("Confirm the latest script before generating the video", show_alert=True); return
    avatar = get_avatar(draft.avatar_key or "")
    if not avatar: await callback.answer("The selected avatar is unavailable", show_alert=True); return
    try:
        motion_prompt = read_motion_prompt(avatar.motion_prompt_key)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    update_draft(draft_id, status=VideoStatus.GENERATING.value, current_step="generating", generation_token=f"draft-{draft_id}", heygen_video_id=None, error_message=None)
    try: video_id = await asyncio.to_thread(HeyGenClient().create_video, avatar.heygen_avatar_id, draft.normalized_text, f"{draft.video_type}-{draft.id}", motion_prompt)
    except HeyGenError as exc:
        update_draft(draft_id, status=VideoStatus.ERROR.value, current_step="final_confirmation", error_message=str(exc)); await callback.message.answer("Video generation could not be started. Check the avatar configuration and try again."); await callback.answer(); return
    update_draft(draft_id, heygen_video_id=video_id)
    await callback.message.answer("The video is being generated. This may take several minutes."); await callback.answer()




@router.callback_query(lambda c: c.data == "menu:main")
async def menu_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message: await callback.message.answer("Main menu.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("nav:"))
async def back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data(); target = callback.data
    if not callback.message: return
    if target == "nav:avatar_back":
        if await state.get_state() != Workflow.selecting_avatar.state:
            await callback.answer("This button belongs to an earlier step", show_alert=True); return
        await state.clear(); await state.set_state(Workflow.choosing_type); await callback.message.answer("Choose a video type.", reply_markup=video_types())
    elif target == "nav:greeting_recipient":
        if await state.get_state() != Workflow.greeting_occasion.state:
            await callback.answer("This button belongs to an earlier step", show_alert=True); return
        if data.get("draft_id"):
            update_draft(data["draft_id"], current_step="greeting_recipient")
        await state.set_state(Workflow.greeting_recipient); await callback.message.answer("Who is the greeting for? You can enter a name, role or team name.", reply_markup=back_main("nav:avatar_back"))
    elif target == "nav:greeting_occasion":
        if await state.get_state() != Workflow.greeting_details.state:
            await callback.answer("This button belongs to an earlier step", show_alert=True); return
        if data.get("draft_id"):
            update_draft(data["draft_id"], current_step="greeting_occasion")
        await state.set_state(Workflow.greeting_occasion); await callback.message.answer("What is the occasion?", reply_markup=back_main("nav:greeting_recipient"))
    elif target == "nav:source":
        if await state.get_state() != Workflow.source_text.state:
            await callback.answer("This button belongs to an earlier step", show_alert=True); return
        if data.get("draft_id"):
            update_draft(data["draft_id"], current_step="source_choice")
        await state.set_state(Workflow.source_choice); await callback.message.answer("How would you like to provide the script?", reply_markup=source_choice())
    elif target == "nav:final_back":
        if await state.get_state() != Workflow.final_confirmation.state:
            await callback.answer("This button belongs to an earlier step", show_alert=True); return
        draft_id = data.get("draft_id")
        if draft_id:
            update_draft(draft_id, current_step="review_text")
            await state.set_state(Workflow.review_text)
            await _show_review(callback.message, draft_id)
        else: await callback.message.answer("Main menu.", reply_markup=main_menu())
    elif target == "nav:review_back":
        draft_id = data.get("draft_id")
        if await state.get_state() in {Workflow.text_correction.state, Workflow.voice_correction.state}:
            if draft_id:
                update_draft(draft_id, current_step="review_text")
                await state.set_state(Workflow.review_text)
                await _show_review(callback.message, draft_id)
            else:
                await callback.message.answer("Main menu.", reply_markup=main_menu())
        elif await state.get_state() == Workflow.review_text.state and draft_id:
            update_draft(draft_id, current_step="selecting_avatar")
            await state.set_state(Workflow.selecting_avatar)
            await show_avatar(callback, state, draft_id, data.get("avatar_index", 0))
        else: await callback.message.answer("Choose a video type.", reply_markup=video_types())
    else: await callback.message.answer("Main menu.", reply_markup=main_menu())
    await callback.answer()
