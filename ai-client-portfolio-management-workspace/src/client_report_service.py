from datetime import date
from pathlib import Path
import re

from src.onepage_service import build_onepage_context


OUTPUT_DIR = Path("outputs")


def _safe_name(value):
    return re.sub(r"[^A-Za-zА-Яа-я0-9_-]+", "_", str(value or "client")).strip("_")


def _line(value):
    return str(value or "").replace("\n", " ").strip()


def _money(value):
    if value is None:
        return ""
    try:
        return f"{round(float(value)):,.0f}".replace(",", " ") + " ₽"
    except (TypeError, ValueError):
        return str(value)


def generate_client_pdf(client_id):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("Для PDF нужен пакет reportlab. Установите: .venv/bin/python -m pip install reportlab") from exc

    font_path = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    pdfmetrics.registerFont(TTFont("PortfolioArial", font_path))
    styles = getSampleStyleSheet()
    title = ParagraphStyle("portfolio_title", parent=styles["Title"], fontName="PortfolioArial", fontSize=16, leading=20, spaceAfter=8)
    heading = ParagraphStyle("portfolio_heading", parent=styles["Heading2"], fontName="PortfolioArial", fontSize=12, leading=15, spaceBefore=8, spaceAfter=5)
    body = ParagraphStyle("portfolio_body", parent=styles["BodyText"], fontName="PortfolioArial", fontSize=9, leading=12)

    context = build_onepage_context(client_id)
    client = context["client"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"Отчет_{_safe_name(client['name'])}_{date.today().isoformat()}.pdf"

    story = [Paragraph(f"Отчёт по клиенту: {client['name']}", title)]
    story.append(Paragraph(f"Сформировано: {date.today().strftime('%d.%m.%Y')}", body))

    def section(name):
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(name, heading))

    def table(rows, widths=None):
        data = [[Paragraph(_line(cell), body) for cell in row] for row in rows]
        item = Table(data, colWidths=widths)
        item.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "PortfolioArial"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(item)

    section("1. Основная информация о клиенте")
    table([
        ["Показатель", "Значение"],
        ["ИНН", client.get("inn") or "Не указан"],
        ["Контактное лицо", client.get("contact_person") or "Не указано"],
        ["Статус клиента", client.get("client_status") or ""],
        ["Отрасль", client.get("industry") or ""],
        ["Сегмент", client.get("segment") or ""],
        ["Оценка клиента", client.get("client_score")],
        ["Проникновение продуктов", client.get("product_penetration") or ""],
    ], [60 * mm, 115 * mm])

    section("2. Описание компании")
    story.append(Paragraph(_line(client.get("company_description") or client.get("business_profile") or "Описание не заполнено."), body))

    section("3. Ключевые показатели")
    indicator_rows = [["Показатель", "Факт", "План", "Выполнение", "Прогноз"]]
    for item in context.get("indicators", [])[:6]:
        indicator_rows.append([item["name"], item["fact"], item["plan"], item["completion"], item["forecast"]])
    table(indicator_rows, [48 * mm, 34 * mm, 34 * mm, 28 * mm, 34 * mm])

    section("4. Проекты клиента")
    rows = [["Проект", "Статус", "Срок", "Прогресс"]]
    for project in context.get("projects", [])[:5]:
        rows.append([project["title"], project["status"], project["planned_end_date"], project["progress_percent"]])
    table(rows, [72 * mm, 35 * mm, 35 * mm, 30 * mm])

    section("5. Задачи и риски")
    rows = [["Пункт", "Статус/причина", "Срок"]]
    for task in context.get("tasks", [])[:4]:
        rows.append([task["title"], task["status"], task["due_date"]])
    for reason in (context.get("risk") or {}).get("risk_reasons", [])[:3]:
        rows.append(["Риск", reason, ""])
    table(rows, [70 * mm, 78 * mm, 28 * mm])

    section("6. Встречи")
    rows = [["Встреча", "Дата", "Следующие шаги"]]
    for meeting in context.get("meetings", [])[:4]:
        rows.append([meeting["title"], meeting["meeting_datetime"], meeting["next_steps"] or meeting["summary"]])
    table(rows, [55 * mm, 35 * mm, 88 * mm])

    section("7. Команда по клиенту")
    rows = [["ФИО", "Роль", "Зона ответственности"]]
    for member in context.get("team", [])[:6]:
        rows.append([member["full_name"], member["role"], member["responsibility"]])
    table(rows, [62 * mm, 38 * mm, 78 * mm])

    section("8. Рекомендации")
    for action in ((context.get("risk") or {}).get("recommended_actions") or (context.get("deviation") or {}).get("recommended_actions") or ["Продолжить мониторинг клиента"])[:5]:
        story.append(Paragraph("• " + _line(action), body))

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    doc.build(story)
    return path
