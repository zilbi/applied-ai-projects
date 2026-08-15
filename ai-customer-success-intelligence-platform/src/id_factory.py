from uuid import uuid4


def new_external_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
