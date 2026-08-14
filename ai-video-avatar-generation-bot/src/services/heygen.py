from __future__ import annotations

import uuid
from typing import Any

import requests

from src.core.config import settings


class HeyGenError(RuntimeError):
    pass


class HeyGenClient:
    CREATE_VIDEO_ENDPOINT = "/v3/videos"
    VIDEO_STATUS_ENDPOINT = "/v3/videos/{video_id}"
    AVATAR_LOOK_ENDPOINT = "/v3/avatars/looks/{avatar_id}"

    def __init__(self) -> None:
        if not settings.heygen_api_key:
            raise HeyGenError("HeyGen is not configured")
        self.base_url = settings.heygen_base_url.rstrip("/")
        self.session = requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "x-api-key": settings.heygen_api_key,
            "Content-Type": "application/json",
            **kwargs.pop("headers", {}),
        }
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=60,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise HeyGenError("The video service could not be reached") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text}
        if not response.ok:
            message = payload.get("message") or payload.get("error") or "unknown error"
            raise HeyGenError(f"The video service rejected the request: {message}")
        data = payload.get("data") or payload
        if not isinstance(data, dict):
            raise HeyGenError("The video service returned an unexpected response")
        return data

    @staticmethod
    def _resolution(width: int, height: int) -> str:
        longest = max(width, height)
        if longest >= 3840:
            return "4k"
        if longest >= 1920:
            return "1080p"
        return "720p"

    @staticmethod
    def _aspect_ratio(width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "16:9"
        ratio = width / height
        known = {"16:9": 16 / 9, "9:16": 9 / 16, "4:5": 4 / 5, "5:4": 5 / 4, "1:1": 1}
        return min(known, key=lambda item: abs(known[item] - ratio))

    @classmethod
    def build_create_video_payload(
        cls,
        *,
        avatar_id: str,
        text: str,
        title: str,
        motion_prompt: str,
        engine_type: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "title": title,
            "aspect_ratio": cls._aspect_ratio(settings.heygen_width, settings.heygen_height),
            "resolution": cls._resolution(settings.heygen_width, settings.heygen_height),
            "output_format": "mp4",
            "script": text,
            "motion_prompt": motion_prompt,
        }
        if engine_type:
            payload["engine"] = {"type": engine_type}
        return payload

    def get_avatar_look(self, avatar_id: str) -> dict[str, Any]:
        return self._request("GET", self.AVATAR_LOOK_ENDPOINT.format(avatar_id=avatar_id))

    @staticmethod
    def _engine_type(avatar_look: dict[str, Any]) -> str | None:
        status = avatar_look.get("status")
        engines = avatar_look.get("supported_api_engines") or []
        if status != "completed":
            detail = avatar_look.get("error") or avatar_look.get("status") or "unknown status"
            raise HeyGenError(f"The avatar is not ready for generation: {detail}")
        if not engines:
            raise HeyGenError("The avatar has no supported API engine")
        # Motion prompts for video avatars require Avatar V. The same digital
        # twin can advertise IV, V and III simultaneously, so preferring IV
        # here would make HeyGen use the default Avatar IV engine and reject
        # the otherwise valid motion_prompt.
        if "avatar_v" in engines:
            return "avatar_v"
        if "avatar_iv" in engines:
            return None
        if "avatar_iii" in engines:
            return "avatar_iii"
        return engines[0]

    def create_video(self, avatar_id: str, text: str, title: str, motion_prompt: str) -> str:
        if not avatar_id:
            raise HeyGenError("No HeyGen avatar ID is configured for the selected avatar")
        avatar_look = self.get_avatar_look(avatar_id)
        engine_type = self._engine_type(avatar_look)
        payload = self.build_create_video_payload(
            avatar_id=avatar_id,
            text=text,
            title=title,
            motion_prompt=motion_prompt,
            engine_type=engine_type,
        )
        data = self._request(
            "POST",
            self.CREATE_VIDEO_ENDPOINT,
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        video_id = data.get("video_id") or data.get("id")
        if not video_id:
            raise HeyGenError("The video service did not return a video ID")
        return str(video_id)

    def status(self, video_id: str) -> tuple[str, str | None, str | None]:
        data = self._request("GET", self.VIDEO_STATUS_ENDPOINT.format(video_id=video_id))
        status = str(data.get("status", "processing")).lower()
        if status in {"completed", "complete", "success", "succeeded"} or data.get("video_url"):
            return "ready", data.get("video_url"), None
        if status in {"failed", "failure", "error"} or data.get("failure_code") or data.get("failure_message"):
            return "error", None, str(data.get("failure_message") or data.get("failure_code") or "Unknown error")
        return "generating", None, None
