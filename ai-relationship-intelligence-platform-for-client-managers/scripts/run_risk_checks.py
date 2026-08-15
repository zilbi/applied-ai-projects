from __future__ import annotations

import argparse
import asyncio

from bootstrap import setup_path

setup_path()

from src.workers.risk_monitoring_job import run_risk_monitoring


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(await run_risk_monitoring(dry_run=args.dry_run))


if __name__ == "__main__":
    asyncio.run(main())
