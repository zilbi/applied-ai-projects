from datetime import date, timedelta

from src import repositories


TASK_STATUS_LABELS = [
    ("open", "New"),
    ("in_progress", "In progress"),
    ("overdue", "Overdue"),
    ("done", "Completed"),
]

DEAL_STAGE_GROUPS = [
    ("Initiated", {"new", "qualification"}),
    ("In progress", {"contract"}),
    ("Proposal", {"proposal"}),
    ("Negotiation", {"negotiation"}),
    ("Closed", {"won"}),
    ("Lost", {"lost"}),
]


def build_dashboard_analytics(clients, tasks, deals, meetings, days=14):
    metrics_by_client = {}
    events_by_client = {}
    for client in clients:
        metrics_by_client[client.id] = repositories.get_metrics_by_client(client.id)
        events_by_client[client.id] = sorted(repositories.get_events_by_client(client.id), key=lambda item: item.event_date)
    return {
        "risk_trend": get_risk_trend(clients, tasks, deals, meetings, metrics_by_client, events_by_client, days=days),
        "task_status_distribution": get_task_status_distribution(tasks),
        "deal_stage_distribution": get_deal_stage_distribution(deals),
        "client_score_distribution": get_client_score_distribution(clients),
        "plan_fact_revenue_summary": get_plan_fact_revenue_summary(metrics_by_client),
    }


def get_risk_trend(clients, tasks, deals, meetings, metrics_by_client, events_by_client, days=14):
    today = date.today()
    series = []
    for offset in range(days - 1, -1, -1):
        point_date = today - timedelta(days=offset)
        risky_clients = 0
        for client in clients:
            risk_score = _historical_risk_score(
                client,
                point_date,
                [task for task in tasks if task.client_id == client.id],
                [deal for deal in deals if deal.client_id == client.id],
                [meeting for meeting in meetings if meeting.client_id == client.id],
                metrics_by_client.get(client.id, []),
                events_by_client.get(client.id, []),
            )
            if risk_score >= 30:
                risky_clients += 1
        series.append({"label": point_date.strftime("%d.%m"), "value": risky_clients, "date": point_date})
    return series


def get_task_status_distribution(tasks):
    today = date.today()
    counts = {"open": 0, "in_progress": 0, "overdue": 0, "done": 0}
    for task in tasks:
        if task.status == "cancelled":
            continue
        status = task.status
        if status == "blocked":
            status = "in_progress"
        elif task.due_date and task.due_date < today and status not in {"done", "cancelled", "overdue"}:
            status = "overdue"
        if status in counts:
            counts[status] += 1
    return [{"key": key, "label": label, "value": counts[key]} for key, label in TASK_STATUS_LABELS]


def get_deal_stage_distribution(deals):
    items = []
    for label, stages in DEAL_STAGE_GROUPS:
        value = sum(1 for deal in deals if deal.stage in stages)
        items.append({"label": label, "value": value})
    return items


def get_client_score_distribution(clients):
    high = sum(1 for client in clients if (client.health_score or 0) >= 80)
    medium = sum(1 for client in clients if 60 <= (client.health_score or 0) < 80)
    low = sum(1 for client in clients if (client.health_score or 0) < 60)
    total = max(1, len(clients))
    return [
        {"label": "Высокая", "value": high, "share": round(high * 100 / total)},
        {"label": "Средняя", "value": medium, "share": round(medium * 100 / total)},
        {"label": "Низкая", "value": low, "share": round(low * 100 / total)},
    ]


def get_plan_fact_revenue_summary(metrics_by_client):
    plan = 0.0
    fact = 0.0
    clients_with_metrics = 0
    for metrics in metrics_by_client.values():
        if not metrics:
            continue
        latest = metrics[-1]
        plan += float(latest.revenue_plan or 0)
        fact += float(latest.revenue_fact or 0)
        clients_with_metrics += 1
    if not clients_with_metrics:
        return None
    gap = max(0.0, plan - fact)
    forecast = fact + gap * 0.55
    return {"plan": round(plan), "fact": round(fact), "forecast": round(forecast)}


def _historical_risk_score(client, point_date, tasks, deals, meetings, metrics, events):
    score = 0
    if (client.health_score or 0) < 60:
        score += 20

    metric = _latest_metric_on_or_before(metrics, point_date)
    if metric and (metric.risk_score or 0) > 70:
        score += 20
    if metric and metric.revenue_plan and (metric.revenue_fact or 0) < 0.75 * metric.revenue_plan:
        score += 20

    if any(_task_is_overdue_on(task, point_date) for task in tasks):
        score += 20

    if any((not deal.commercial_offer_exists) and ((deal.last_activity_date is None) or deal.last_activity_date <= point_date) for deal in deals):
        score += 10

    stale_cutoff = point_date - timedelta(days=21)
    if any(deal.last_activity_date and deal.last_activity_date < stale_cutoff for deal in deals):
        score += 10

    if not any(meeting.status == "planned" and meeting.meeting_datetime.date() >= point_date for meeting in meetings):
        score += 10

    negative_cutoff = point_date - timedelta(days=14)
    if any(event.impact == "negative" and negative_cutoff <= event.event_date.date() <= point_date for event in events):
        score += 10

    return min(score, 100)


def _latest_metric_on_or_before(metrics, point_date):
    latest = None
    for metric in metrics:
        if metric.metric_date <= point_date:
            latest = metric
        else:
            break
    return latest


def _task_is_overdue_on(task, point_date):
    created_at = task.created_at.date() if task.created_at else None
    if created_at and created_at > point_date:
        return False
    if not task.due_date or task.due_date >= point_date:
        return False
    return task.status not in {"done", "cancelled"}
