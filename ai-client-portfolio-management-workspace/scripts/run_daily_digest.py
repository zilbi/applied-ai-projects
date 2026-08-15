from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.daily_digest_service import save_daily_digest
from src.db import init_db


def main():
    init_db()
    digest = save_daily_digest(use_gigachat=False)
    print(f"DailyDigest: {digest.status} {digest.digest_date} {digest.id}")
    print(digest.digest_text)


if __name__ == "__main__":
    main()
