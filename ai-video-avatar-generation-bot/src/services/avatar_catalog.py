from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.core.config import ROOT
from src.core.config import settings


@dataclass(frozen=True)
class Avatar:
    id: str
    name: str
    person_name: str
    style_name: str
    description: str
    heygen_avatar_id: str
    motion_prompt_key: str
    demo_video: str
    active: bool


def _avatar_from_config(item: dict) -> Avatar:
    values = settings.model_dump(by_alias=True)
    avatar_id = str(values.get(item["heygen_avatar_id_env"], "")).strip()
    person_name = settings.avatar_person_name.strip()
    style_name = item["style_name"]
    name = (
        item["name_template"].format(person_name=person_name)
        if person_name
        else f"Avatar — {style_name.lower()}"
    )
    return Avatar(
        id=item["id"],
        name=name,
        person_name=person_name,
        style_name=style_name,
        description=item["description"],
        heygen_avatar_id=avatar_id,
        motion_prompt_key=item["motion_prompt_key"],
        demo_video=item.get("demo_video", ""),
        active=bool(item.get("active", False)),
    )


def active_avatars() -> list[Avatar]:
    raw = json.loads((ROOT / "config" / "avatars.json").read_text(encoding="utf-8"))
    return [_avatar_from_config(item) for item in raw if item.get("active")]


def get_avatar(avatar_id: str) -> Avatar | None:
    return next((avatar for avatar in active_avatars() if avatar.id == avatar_id), None)


def read_motion_prompt(prompt_key: str) -> str:
    path = Path(ROOT, "templates", "motion_prompts", f"{prompt_key}.txt")
    if not path.is_file():
        raise ValueError(f"Motion prompt not found for avatar: {prompt_key}")
    prompt = " ".join(path.read_text(encoding="utf-8").split())
    if not prompt:
        raise ValueError(f"Motion prompt is empty: {path.name}")
    return prompt


def preview_path(avatar: Avatar) -> Path | None:
    if not avatar.demo_video or avatar.demo_video.startswith(("http://", "https://")):
        return None
    return ROOT / avatar.demo_video
