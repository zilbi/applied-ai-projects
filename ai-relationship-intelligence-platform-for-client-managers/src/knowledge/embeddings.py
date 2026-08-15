from __future__ import annotations

import hashlib


def keyword_embedding(text: str, size: int = 384) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    while len(values) < size:
        values.extend(byte / 255 for byte in digest)
    return values[:size]
