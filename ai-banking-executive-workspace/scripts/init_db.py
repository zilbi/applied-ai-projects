from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auth import create_user
from src.db import LOCAL_DB_PATH, init_db
from src.repositories import get_user_by_login


def main():
    Path(LOCAL_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db()
    users = [
        ("admin", "admin", "Администратор системы", "admin"),
        ("sponsor", "sponsor", "Председатель / Спонсор", "sponsor"),
        ("manager", "manager", "Менеджер-исполнитель", "manager"),
    ]
    for login, password, full_name, role in users:
        if not get_user_by_login(login):
            create_user(login, password, full_name, role)
    print(f"Database initialized: {LOCAL_DB_PATH}")
    print("")
    print("Тестовые пользователи:")
    print("admin / admin")
    print("sponsor / sponsor")
    print("manager / manager")


if __name__ == "__main__":
    main()
