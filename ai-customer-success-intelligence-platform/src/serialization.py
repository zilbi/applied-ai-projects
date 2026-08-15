from __future__ import annotations

from typing import Any


def public_dict(obj: Any) -> dict[str, Any]:
    data = {}
    for column in obj.__table__.columns:
        if column.name == "password_hash":
            continue
        data[column.name] = getattr(obj, column.name)
    return data
