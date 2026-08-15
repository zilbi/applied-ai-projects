from __future__ import annotations

import asyncio

from bootstrap import setup_path

setup_path()

from src.ai.report_generator import generate_risk_report
from src.db import SessionLocal
from src.schemas import GenerateReportRequest


async def main() -> None:
    async with SessionLocal() as session:
        print(await generate_risk_report(session, GenerateReportRequest()))


if __name__ == "__main__":
    asyncio.run(main())
