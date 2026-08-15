from __future__ import annotations

import argparse
import asyncio

from bootstrap import setup_path

setup_path()

from src.ai.synthetic_data_service import generate_seed
from src.db import SessionLocal
from src.schemas import GenerateSeedRequest


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--industry", default="retail")
    parser.add_argument("--confirm-generate", action="store_true")
    args = parser.parse_args()
    async with SessionLocal() as session:
        result = await generate_seed(
            session,
            GenerateSeedRequest(clients=args.clients, industry=args.industry, confirm_generate=args.confirm_generate),
        )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
