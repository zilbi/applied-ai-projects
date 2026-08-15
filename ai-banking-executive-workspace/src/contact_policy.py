from datetime import date, timedelta

from src import repositories


CONTACT_INTERVALS = {
    "high": 7,
    "medium": 14,
    "low": 30,
}


def _interval_for_priority(priority):
    return CONTACT_INTERVALS.get((priority or "").lower(), 14)


def check_contact_policy(client_id):
    client = repositories.get_client_by_id(client_id)
    if not client:
        raise LookupError("Client not found")
    interval_days = _interval_for_priority(client.priority)
    last_contact = client.last_contact_date
    next_due = client.next_contact_due
    today = date.today()
    violation = False
    message = "Контактная политика соблюдается"
    if next_due and next_due < today:
        violation = True
        message = f"Плановый контакт просрочен: {next_due}"
    elif last_contact and last_contact < today - timedelta(days=interval_days):
        violation = True
        message = f"Последний контакт старше {interval_days} дней: {last_contact}"
    elif not last_contact:
        violation = True
        message = "Нет даты последнего контакта"
    return {
        "client_id": client_id,
        "priority": client.priority,
        "interval_days": interval_days,
        "violation": violation,
        "message": message,
    }


def get_clients_with_contact_policy_violations():
    violations = []
    for client in repositories.get_clients_for_user(type("AdminUser", (), {"role": "admin"})()):
        check = check_contact_policy(client.id)
        if check["violation"]:
            violations.append({"client": client, "check": check})
    return violations


def create_contact_policy_notifications():
    created = 0
    system_user = type("SystemUser", (), {"id": None, "role": "admin"})()
    for item in get_clients_with_contact_policy_violations():
        client = item["client"]
        check = item["check"]
        try:
            repositories.create_client_event(system_user, client.id, "contact_policy_violation", "Contact policy violation", check["message"], "negative")
            created += 1
        except Exception:
            continue
    return created
