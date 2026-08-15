from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import SuccessCase


async def search_success_cases(session: AsyncSession, query: str, limit: int = 5) -> list[dict]:
    if not query:
        result = await session.execute(select(SuccessCase).order_by(SuccessCase.created_at.desc()).limit(limit))
    else:
        pattern = f"%{query.lower()}%"
        result = await session.execute(
            select(SuccessCase)
            .where(
                or_(
                    SuccessCase.title.ilike(pattern),
                    SuccessCase.problem.ilike(pattern),
                    SuccessCase.solution.ilike(pattern),
                    SuccessCase.result.ilike(pattern),
                )
            )
            .limit(limit)
        )
    return [
        {
            "id": case.id,
            "title": case.title,
            "problem": case.problem,
            "solution": case.solution,
            "result": case.result,
            "tags": case.tags,
        }
        for case in result.scalars()
    ]
