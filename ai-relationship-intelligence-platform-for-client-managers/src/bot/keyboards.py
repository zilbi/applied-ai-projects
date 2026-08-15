from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def add_navigation_buttons(keyboard: InlineKeyboardMarkup, back_callback: str | None = None) -> InlineKeyboardMarkup:
    rows = [list(row) for row in keyboard.inline_keyboard]
    nav_row = []
    if back_callback:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    nav_row.append(InlineKeyboardButton(text="🏠 На главную", callback_data="home"))
    if not _has_callbacks(rows, {button.callback_data for button in nav_row if button.callback_data}):
        rows.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_home_keyboard(back_callback: str | None = None) -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=[]), back_callback)


def _has_callbacks(rows: list[list[InlineKeyboardButton]], callbacks: set[str]) -> bool:
    current = {button.callback_data for row in rows for button in row if button.callback_data}
    return bool(current.intersection(callbacks))


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Мой день", callback_data="my_day"),
                InlineKeyboardButton(text="🤖 Спросить AI", callback_data="ask_ai"),
            ],
            [
                InlineKeyboardButton(text="📋 Задачи", callback_data="tasks"),
                InlineKeyboardButton(text="⚠️ Риски", callback_data="risks"),
            ],
            [
                InlineKeyboardButton(text="📅 Календарь", callback_data="calendar"),
                InlineKeyboardButton(text="👥 Клиенты", callback_data="clients"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Генерация", callback_data="generation"),
                InlineKeyboardButton(text="📚 Кейсы", callback_data="cases"),
            ],
        ]
    )


def my_day_keyboard() -> InlineKeyboardMarkup:
    return main_menu()


def my_day_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚠️ Все риски", callback_data="risks"),
                InlineKeyboardButton(text="📋 Открыть задачи", callback_data="tasks"),
            ],
            [
                InlineKeyboardButton(text="📅 Встречи сегодня", callback_data="calendar"),
                InlineKeyboardButton(text="🤖 Спросить AI", callback_data="ask_ai"),
            ],
        ]
    )


def ai_keyboard() -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Что требует внимания?", callback_data="ai_quick:attention")],
            [InlineKeyboardButton(text="📋 Какие задачи горят?", callback_data="ai_quick:tasks")],
            [InlineKeyboardButton(text="📅 К каким встречам подготовиться?", callback_data="ai_quick:calendar")],
            [InlineKeyboardButton(text="👥 Какие клиенты в риске?", callback_data="ai_quick:risks")],
        ]
    ))


def ask_ai_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Спросить AI", callback_data="ask_ai")],
            [InlineKeyboardButton(text="🏠 На главную", callback_data="home")],
        ]
    )


def tasks_keyboard(tasks, has_more: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for idx, task in enumerate(tasks, start=1):
        rows.append(
            [
                InlineKeyboardButton(text=f"✅ Закрыть {idx}", callback_data=f"task_close:{task.id}"),
                InlineKeyboardButton(text=f"🔁 Перенести {idx}", callback_data=f"task_reschedule:{task.id}"),
                InlineKeyboardButton(text=f"🤖 Спросить AI {idx}", callback_data=f"task_ai:{task.id}"),
            ]
        )
    if has_more:
        rows.append([InlineKeyboardButton(text="Показать ещё", callback_data="tasks_more")])
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=rows))


def reschedule_keyboard(kind: str, item_id: int, back_callback: str | None = None) -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="завтра", callback_data=f"{kind}_move:{item_id}:1"),
                InlineKeyboardButton(text="через 3 дня", callback_data=f"{kind}_move:{item_id}:3"),
            ],
            [InlineKeyboardButton(text="выбрать дату вручную", callback_data=f"{kind}_manual:{item_id}")],
        ]
    ), back_callback)


def risks_keyboard(risks, has_more: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for idx, risk in enumerate(risks, start=1):
        rows.append(
            [
                InlineKeyboardButton(text=f"📋 Задача {idx}", callback_data=f"risk_task:{risk.id}"),
                InlineKeyboardButton(text=f"✉️ Письмо {idx}", callback_data=f"risk_email:{risk.id}"),
                InlineKeyboardButton(text=f"🤖 Спросить AI {idx}", callback_data=f"risk_ai:{risk.id}"),
            ]
        )
    if has_more:
        rows.append([InlineKeyboardButton(text="Показать ещё", callback_data="risks_more")])
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=rows))


def calendar_keyboard(events, has_more: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for idx, event in enumerate(events, start=1):
        rows.append(
            [
                InlineKeyboardButton(text=f"🤖 Подготовить {idx}", callback_data=f"event_brief:{event.id}"),
                InlineKeyboardButton(text=f"✅ Проведена {idx}", callback_data=f"event_done:{event.id}"),
                InlineKeyboardButton(text=f"🔁 Перенести {idx}", callback_data=f"event_reschedule:{event.id}"),
            ]
        )
    if has_more:
        rows.append([InlineKeyboardButton(text="Показать ещё", callback_data="calendar_more")])
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=rows))


def clients_keyboard(clients, has_more: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"👤 {idx}", callback_data=f"client_card:{client.id}") for idx, client in enumerate(clients, start=1)]]
    rows.append(
        [
            InlineKeyboardButton(text="🔍 Найти клиента", callback_data="client_find"),
            InlineKeyboardButton(text="⚠️ Только рисковые", callback_data="clients_risky"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🤖 Спросить AI", callback_data="ask_ai")])
    if has_more:
        rows.append([InlineKeyboardButton(text="Показать ещё", callback_data="clients_more")])
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=rows))


def client_card_keyboard(client_id: int) -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Создать задачу", callback_data=f"client_task:{client_id}"),
                InlineKeyboardButton(text="✉️ Сгенерировать письмо", callback_data=f"client_email:{client_id}"),
            ],
            [InlineKeyboardButton(text="🤖 Спросить AI", callback_data=f"client_ai:{client_id}")],
        ]
    ), "clients")


def generation_keyboard() -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Отчёт по рискам", callback_data="gen_preview:report")],
            [InlineKeyboardButton(text="✉️ Письмо клиенту", callback_data="gen_preview:email")],
            [InlineKeyboardButton(text="🧪 Гипотеза удержания", callback_data="gen_preview:hypothesis")],
            [InlineKeyboardButton(text="📊 CSV с метриками", callback_data="gen_preview:csv")],
        ]
    ))


def generation_confirm_keyboard(kind: str) -> InlineKeyboardMarkup:
    return add_navigation_buttons(InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"gen_confirm:{kind}"),
                InlineKeyboardButton(text="Отменить", callback_data=f"gen_cancel:{kind}"),
            ]
        ]
    ), "generation")


def cases_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏥 ИИ в медицине", callback_data="case:medicine")],
        [InlineKeyboardButton(text="🏢 ИИ в недвижимости", callback_data="case:realty")],
        [InlineKeyboardButton(text="🛒 ИИ в ритейле", callback_data="case:retail")],
        [InlineKeyboardButton(text="💳 ИИ в финансах", callback_data="case:finance")],
        [InlineKeyboardButton(text="🚚 ИИ в логистике", callback_data="case:logistics")],
        [InlineKeyboardButton(text="🎓 ИИ в образовании", callback_data="case:education")],
    ]
    return add_navigation_buttons(InlineKeyboardMarkup(inline_keyboard=rows))


def case_detail_keyboard(case_key: str) -> InlineKeyboardMarkup:
    return add_navigation_buttons(
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Спросить AI / 🎙 голосом", callback_data=f"case_ai:{case_key}")],
            ]
        ),
        "cases",
    )
