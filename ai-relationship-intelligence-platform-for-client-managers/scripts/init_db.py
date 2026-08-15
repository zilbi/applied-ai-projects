from __future__ import annotations

import asyncio

from bootstrap import setup_path

setup_path()

from src.db import create_all


async def main() -> None:
    await create_all()
    print("Database schema is ready.")


if __name__ == "__main__":
    asyncio.run(main())
