from __future__ import annotations

import argparse
import asyncio

from bootstrap import setup_path

setup_path()

from src.workers.weekly_digest_job import run_weekly_digest


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-send", action="store_true")
    args = parser.parse_args()
    print(await run_weekly_digest(dry_run=args.dry_run or not args.confirm_send, confirm_send=args.confirm_send))


if __name__ == "__main__":
    asyncio.run(main())
