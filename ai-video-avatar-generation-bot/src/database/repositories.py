from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from src.database.models import User, VideoDraft, VideoStatus
from src.database.session import SessionLocal


def ensure_user(telegram_id: int, display_name: str) -> None:
    with SessionLocal() as session:
        user = session.get(User, telegram_id)
        if user is None:
            session.add(User(telegram_id=telegram_id, display_name=display_name))
        else:
            user.display_name = display_name
        session.commit()


def create_draft(user_id: int, video_type: str, current_step: str | None = None) -> VideoDraft:
    with SessionLocal() as session:
        draft = VideoDraft(user_id=user_id, video_type=video_type, current_step=current_step)
        session.add(draft); session.commit(); session.refresh(draft)
        return draft


def get_draft(draft_id: int, user_id: int | None = None) -> VideoDraft | None:
    with SessionLocal() as session:
        query = select(VideoDraft).where(VideoDraft.id == draft_id)
        if user_id is not None:
            query = query.where(VideoDraft.user_id == user_id)
        return session.scalar(query)


def get_user_draft(draft_id: int, user_id: int) -> VideoDraft | None:
    return get_draft(draft_id, user_id)


def update_draft(draft_id: int, **values: Any) -> VideoDraft:
    with SessionLocal() as session:
        draft = session.get(VideoDraft, draft_id)
        if draft is None:
            raise LookupError("Draft not found")
        for key, value in values.items():
            setattr(draft, key, value)
        session.commit(); session.refresh(draft)
        return draft


def append_revision(draft_id: int, instruction: str, text: str) -> VideoDraft:
    draft = get_draft(draft_id)
    if draft is None: raise LookupError("Draft not found")
    history = list(draft.revisions or [])
    history.append({"at": datetime.now(timezone.utc).isoformat(), "instruction": instruction, "text": text})
    return update_draft(draft_id, revisions=history, current_text=text, normalized_text=None, status=VideoStatus.DRAFT.value)


def list_videos(user_id: int, limit: int = 10) -> list[VideoDraft]:
    with SessionLocal() as session:
        return list(session.scalars(select(VideoDraft).where(VideoDraft.user_id == user_id).order_by(VideoDraft.created_at.desc()).limit(limit)))


def generating_drafts() -> list[VideoDraft]:
    with SessionLocal() as session:
        return list(session.scalars(select(VideoDraft).where(VideoDraft.status == VideoStatus.GENERATING.value, VideoDraft.heygen_video_id.is_not(None))))
