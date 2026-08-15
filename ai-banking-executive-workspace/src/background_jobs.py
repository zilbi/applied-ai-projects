from src import repositories
from src.contact_policy import create_contact_policy_notifications
from src.daily_digest_service import save_daily_digest
from src.event_engine import detect_overdue_tasks


def _run(run_type, callback):
    run = repositories.start_background_check_run(run_type)
    try:
        result = callback()
        summary = result if isinstance(result, str) else f"Created/updated: {result}"
        return repositories.finish_background_check_run(run.id, "success", summary, created_notifications_count=int(result or 0) if isinstance(result, int) else 0, created_events_count=int(result or 0) if isinstance(result, int) else 0)
    except Exception as exc:
        return repositories.finish_background_check_run(run.id, "failed", str(exc), 0, 0)


def run_overdue_tasks_check():
    return _run("overdue_tasks", detect_overdue_tasks)


def run_roadmap_delays_check():
    return _run("roadmap_delays", repositories.detect_roadmap_delays)


def run_team_completeness_check():
    def check_all():
        count = 0
        admin = type("AdminUser", (), {"role": "admin"})()
        for project in repositories.get_projects_for_user(admin):
            result = repositories.check_project_team_completeness(project.id)
            if result["missing_roles"]:
                count += 1
        return count

    return _run("team_completeness", check_all)


def run_contact_policy_check():
    return _run("contact_policy", create_contact_policy_notifications)


def run_new_data_reaction_check():
    def check():
        from src.event_engine import handle_new_data_inserted

        # Lightweight local reaction pass for existing risky records.
        count = 0
        for news in repositories.get_recent_negative_news(limit=20):
            handle_new_data_inserted("ClientNews", news.id)
            count += 1
        return count

    return _run("new_data_reaction", check)


def run_daily_digest_job():
    def generate():
        digest = save_daily_digest(use_gigachat=False)
        return f"Daily digest ready: {digest.id}"

    return _run("daily_digest", generate)


def run_all_background_checks():
    return [
        run_overdue_tasks_check(),
        run_roadmap_delays_check(),
        run_team_completeness_check(),
        run_contact_policy_check(),
        run_new_data_reaction_check(),
        run_daily_digest_job(),
    ]
