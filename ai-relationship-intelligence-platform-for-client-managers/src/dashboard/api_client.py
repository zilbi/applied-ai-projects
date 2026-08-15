from __future__ import annotations

import requests

from src.config import settings


def api_get(path: str, default):
    try:
        response = requests.get(f"{settings.api_base_url}{path}", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return default
