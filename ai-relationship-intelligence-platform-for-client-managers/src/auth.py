from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import User


async def get_current_user(
    x_user_id: Optional[int] = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    if x_user_id:
        return await session.get(User, x_user_id)
    result = await session.execute(select(User).order_by(User.id).limit(1))
    return result.scalar_one_or_none()
