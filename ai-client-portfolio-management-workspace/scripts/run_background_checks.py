from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.background_jobs import run_all_background_checks
from src.db import init_db


def main():
    init_db()
    runs = run_all_background_checks()
    for run in runs:
        print(f"{run.run_type}: {run.status} - {run.result_summary}")


if __name__ == "__main__":
    main()
