from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from queue import Empty, Queue
from time import monotonic
import threading

import pygame
from sqlalchemy import select

from src import background_jobs, client_report_service, daily_digest_service, meeting_brief_service, onepage_service
from src.contact_policy import check_contact_policy, get_clients_with_contact_policy_violations
from src import permissions, repositories
from src.assistant import assistant_service
from src.dashboard_analytics import build_dashboard_analytics
from src.voice_input import transcribe_microphone
from src.db import get_session
from src.models import Client, Deal, Meeting, Message, Metric, Project, RoadmapStep, Task, TaskComment, User
from src.risk_engine import calculate_client_risk
from src.templates_engine import list_templates, load_template, render_template
from src.ui.components import (
    AssistantChatPanel,
    AssistantFloatingButton,
    Button,
    Checkbox,
    Modal,
    MultiLineTextInput,
    NotificationBell,
    PasswordInput,
    ScrollableList,
    ScrollableTable,
    SearchBox,
    SelectBox,
    TextInput,
    Toast,
    UI_DEBUG_HITBOXES,
    UI_DEBUG_FOCUS,
    draw_panel,
    draw_text,
    ellipsize,
)
from src.ui.theme import COLORS, HEIGHT, WIDTH


MAIN_TAB = "Панель"
ONEPAGE_TAB = "Справка клиента"
DAILY_DIGEST_TAB = "Ежедневная сводка"
SECTION_TABS = ["Клиенты", "Проекты", "Задачи", "Сделки", "Календарь", "Показатели", ONEPAGE_TAB, DAILY_DIGEST_TAB, "Сообщения", "Шаблоны", "Уведомления"]
DEMO_TABLE_LIMIT = 5
DEMO_DASHBOARD_LIMIT = 4
ROLE_SECTIONS = {
    "admin": SECTION_TABS,
    "sponsor": ["Клиенты", "Проекты", "Задачи", "Сделки", "Календарь", "Показатели", ONEPAGE_TAB, DAILY_DIGEST_TAB, "Сообщения", "Уведомления"],
    "manager": ["Задачи", "Сообщения"],
}
QUICK_ASSISTANT_QUESTIONS = [
    ("Сводка", "Сделай краткую сводку на сегодня"),
    ("Риски", "Какие клиенты и сделки сейчас в зоне риска?"),
    ("Просроченные задачи", "Какие задачи просрочены и что требует внимания?"),
    ("Сделки без КП", "Какие сделки без коммерческого предложения?"),
    ("Встречи сегодня", "Какие встречи сегодня и к чему подготовиться?"),
    ("Показатели", "У кого ухудшились показатели?"),
]

TEMPLATE_NAMES = {
    "meeting_brief.txt": "Подготовка к встрече",
    "new_client_data_alert.txt": "Новые данные по клиенту",
    "meeting_reminder.txt": "Напоминание о встрече",
    "overdue_task_alert.txt": "Просроченная задача",
    "task_created_alert.txt": "Новая задача",
    "task_updated_alert.txt": "Обновление задачи",
    "daily_digest_draft.txt": "Ежедневная сводка",
}

PRIORITY_LABELS = {"low": "низкий", "medium": "средний", "high": "высокий"}
STAGE_LABELS = {
    "new": "новая",
    "discovery": "выявление потребностей",
    "qualification": "квалификация",
    "proposal": "коммерческое предложение",
    "contract": "договор",
    "negotiation": "переговоры",
    "implementation": "внедрение",
    "support": "сопровождение",
    "won": "выиграна",
    "lost": "проиграна",
}
STATUS_LABELS = {
    "active": "активен",
    "closed": "закрыт",
    "open": "открыта",
    "in_progress": "в работе",
    "blocked": "заблокирована",
    "done": "закрыта",
    "overdue": "просрочена",
    "cancelled": "отменена",
    "planned": "запланирована",
    "completed": "завершена",
    "delayed": "с задержкой",
    "read": "прочитано",
    "unread": "не прочитано",
    "draft": "черновик",
    "ready": "готова",
    "sent": "отправлена",
    "missing": "не хватает",
    "replaced": "заменён",
    "inactive": "неактивен",
    "positive": "положительное",
    "neutral": "нейтральное",
    "negative": "негативное",
}
ROLE_LABELS = {
    "admin": "администратор",
    "sponsor": "спонсор",
    "manager": "менеджер",
    "lawyer": "юрист",
    "risk_manager": "риск-менеджер",
    "product_owner": "владелец продукта",
    "analyst": "аналитик",
    "coordinator": "координатор",
}
NOTIFICATION_TYPE_LABELS = {
    "risk_alert": "Риск",
    "task_changed": "Изменение задачи",
    "task_status_changed": "Статус задачи",
    "meeting_reminder": "Встреча",
    "system_alert": "Системное",
    "task_update": "Обновление задачи",
    "new_task": "Новая задача",
}


def _ru(value):
    if value is None:
        return ""
    text = str(value)
    return STAGE_LABELS.get(text, STATUS_LABELS.get(text, PRIORITY_LABELS.get(text, ROLE_LABELS.get(text, NOTIFICATION_TYPE_LABELS.get(text, text)))))


def _ru_options(values, labels):
    return ["Все"] + [labels.get(value, value) for value in values]


def _code_from_ru(value, labels):
    reverse = {label: code for code, label in labels.items()}
    return reverse.get(value, value)


def _dashboard_reason_label(value):
    text = str(value or "").lower()
    if "просроч" in text:
        return "просрочка"
    if "нет будущей встречи" in text or "назначить встреч" in text:
        return "нет встречи"
    if "коммерческ" in text or "кп" in text:
        return "нет КП"
    if "контакт" in text:
        return "контакт"
    if "команд" in text or "роль" in text:
        return "команда"
    if "delay" in text or "задерж" in text:
        return "задержка"
    if "выручк" in text or "план" in text:
        return "ниже плана"
    if "новост" in text:
        return "новости"
    if "риск" in text:
        return "высокий риск"
    return "внимание"


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _fmt_money(value):
    if value in (None, ""):
        return ""
    try:
        return f"{round(float(value)):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fmt_number(value):
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(numeric)) if numeric.is_integer() else str(round(numeric, 2))


def _parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def _contains(row, query):
    if not query:
        return True
    query = query.lower()
    return any(query in str(value).lower() for value in row.values())


class UIRenderer:
    def __init__(self, state, fonts):
        self.state = state
        self.fonts = fonts
        self.widgets = []
        self.tables = []
        self.assistant_widgets = []
        self.modal_widgets = []
        self.modal_fields = []
        self.assistant_results = Queue()
        self.voice_results = Queue()
        self.voice_stop_event = None
        self.base_surface_cache = None
        self.base_surface_cache_key = None
        self.base_widgets_cache = []
        self.base_tables_cache = []
        self.data_cache_key = None
        self.data_cache = None
        self.data_cache_at = 0.0
        self.risk_cache = {}
        self.analytics_cache = {}
        self.notification_summary_cache = None
        self.notification_summary_at = 0.0

    def handle_event(self, event):
        components = self._event_components()
        if self._handle_assistant_event(event):
            return True

        if self.state.modal:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.close_modal()
                return True
            active = self._active_text_input(self.modal_widgets)
            if event.type == pygame.KEYDOWN and active:
                if event.key == pygame.K_RETURN and not isinstance(active, MultiLineTextInput):
                    self.save_modal_from_state()
                    return True
                if active.handle_event(event):
                    self.sync_widget(active)
                    return True
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self.save_modal_from_state()
                return True
            opened = self._opened_select(self.modal_widgets)
            if opened and opened.handle_event(event):
                self.sync_widget(opened)
                return True
            for widget in self._sort_components(self.modal_widgets):
                if widget.handle_event(event):
                    self.sync_widget(widget)
                    return True
            return True

        opened = self._opened_select(components)
        if opened and opened.handle_event(event):
            self.sync_widget(opened)
            return True

        active = self._active_text_input(components)
        if event.type == pygame.KEYDOWN and active:
            if active.handle_event(event):
                self.sync_widget(active)
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.state.focused_input_key = None
            if self.state.notification_panel_open and not self._click_in_notification_panel(event.pos):
                bell = next((item for item in components if isinstance(item, NotificationBell) and item.rect.collidepoint(event.pos)), None)
                if not bell:
                    self.state.notification_panel_open = False
                    return True
            if self.state.sections_menu_open and not self._click_in_sections_menu(event.pos):
                menu_button = next((item for item in components if getattr(item, "name", "") == "sections_button" and item.rect.collidepoint(event.pos)), None)
                if not menu_button:
                    self.state.sections_menu_open = False
                    return True

        for component in self._sort_components(components):
            if component.handle_event(event):
                self.sync_widget(component)
                return True
        return False

    def _event_components(self):
        return self.widgets + self.tables

    def _assistant_can_handle(self):
        return bool(self.state.current_user and permissions.can_use_assistant(self.state.current_user))

    def _handle_assistant_event(self, event):
        if not self._assistant_can_handle():
            return False
        button_rect = pygame.Rect(WIDTH - 86, HEIGHT - 84, 68, 52)
        if not self.state.assistant_open:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and button_rect.collidepoint(event.pos):
                self.toggle_assistant()
                return True
            return False

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close_assistant()
            return True

        active = self._active_text_input(self.assistant_widgets)
        if event.type == pygame.KEYDOWN and active:
            if event.key == pygame.K_RETURN and not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                self.sync_widget(active)
                self.ask_assistant()
                return True
            if active.handle_event(event):
                self.sync_widget(active)
                return True

        for widget in self._sort_components(self.assistant_widgets):
            if widget.handle_event(event):
                self.sync_widget(widget)
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._click_in_assistant_panel(event.pos):
                return True
            self.state.focused_input_key = None
            return False

        return self._click_in_assistant_panel(pygame.mouse.get_pos()) and event.type in {pygame.MOUSEWHEEL}

    def _sort_components(self, components):
        return sorted(components, key=lambda item: getattr(item, "z_index", 0), reverse=True)

    def _component_key(self, widget):
        return getattr(widget, "state_key", None)

    def _active_text_input(self, components):
        key = self.state.focused_input_key
        if not key:
            return None
        return next((item for item in components if isinstance(item, TextInput) and self._component_key(item) == key), None)

    def _opened_select(self, components):
        key = self.state.open_select_key
        if not key:
            return None
        return next((item for item in components if isinstance(item, SelectBox) and self._component_key(item) == key), None)

    def _click_in_notification_panel(self, pos):
        rect = pygame.Rect(WIDTH - 390, 78, 372, HEIGHT - 96)
        return rect.collidepoint(pos)

    def _sections_menu_rect(self):
        tabs = self.visible_sections()
        label_width = 0
        if getattr(self, "fonts", None):
            label_width = max((self.fonts["small"].size(tab)[0] for tab in tabs), default=0)
        width = max(228, min(320, label_width + 44))
        # 52px header offset + 30px button + 38px row pitch + bottom padding
        content_height = 60 + len(tabs) * 38
        height = min(HEIGHT - 88, max(96, content_height))
        return pygame.Rect(136, 64, width, height)

    def _click_in_sections_menu(self, pos):
        return self._sections_menu_rect().collidepoint(pos)

    def _assistant_panel_rect(self):
        return pygame.Rect(WIDTH - 520 - 24, HEIGHT - 640 - 24, 520, 640)

    def _click_in_assistant_panel(self, pos):
        return self._assistant_panel_rect().collidepoint(pos)

    def sync_widget(self, widget):
        key = getattr(widget, "state_key", None)
        if isinstance(widget, TextInput):
            self.state.focused_input_key = key if widget.focused else None
        if isinstance(widget, SelectBox):
            self.state.open_select_key = key if widget.opened else None
        if not key:
            return
        scope, name = key
        value = widget.checked if isinstance(widget, Checkbox) else getattr(widget, "value", "")
        if scope == "filters":
            self.state.filters[name] = value
            self.base_surface_cache = None
        elif scope == "login":
            setattr(self.state, name, value)
            self.state.focused_input = name
            self.state.focused_input_key = key if getattr(widget, "focused", False) else None
        elif scope == "modal":
            self.state.modal["values"][name] = value
        elif scope == "template":
            self.state.template_drafts[name] = value
        elif scope == "assistant":
            if name == "question":
                self.state.assistant_question = value

    def draw(self, surface):
        self.widgets = []
        self.tables = []
        self.assistant_widgets = []
        self.modal_widgets = []
        self.poll_voice_results()
        self.poll_assistant_results()
        mouse = pygame.mouse.get_pos()
        self.state.mouse_pos = mouse

        if not self.state.current_user:
            self.draw_login(surface, mouse)
            return

        base_key = (getattr(self.state.current_user, "id", None), self.state.active_tab, self.state.notification_panel_open, self.state.sections_menu_open)
        if self.state.assistant_open and self.base_surface_cache is not None and self.base_surface_cache_key == base_key:
            surface.blit(self.base_surface_cache, (0, 0))
            self.widgets = list(self.base_widgets_cache)
            self.tables = list(self.base_tables_cache)
            self.draw_assistant_overlay(surface, mouse)
            if UI_DEBUG_HITBOXES:
                self.draw_debug_hitboxes(surface, mouse)
            self.draw_toasts(surface)
            return

        self.draw_top_bar(surface, mouse)
        if self.state.active_tab == MAIN_TAB:
            self.draw_dashboard(surface, mouse)
        elif self.state.active_tab == "Клиенты":
            self.draw_clients(surface, mouse)
        elif self.state.active_tab == "Проекты":
            self.draw_projects(surface, mouse)
        elif self.state.active_tab == "Задачи":
            self.draw_tasks(surface, mouse)
        elif self.state.active_tab == "Сделки":
            self.draw_deals(surface, mouse)
        elif self.state.active_tab == "Календарь":
            self.draw_calendar(surface, mouse)
        elif self.state.active_tab == "Показатели":
            self.draw_metrics(surface, mouse)
        elif self.state.active_tab == ONEPAGE_TAB:
            self.draw_onepage_screen(surface, mouse)
        elif self.state.active_tab == DAILY_DIGEST_TAB:
            self.draw_daily_digest_screen(surface, mouse)
        elif self.state.active_tab == "Сообщения":
            self.draw_messages(surface, mouse)
        elif self.state.active_tab == "Уведомления":
            self.draw_notifications_screen(surface, mouse)
        elif self.state.active_tab == "Шаблоны":
            self.draw_templates(surface, mouse)

        if self.state.sections_menu_open:
            self.draw_sections_menu(surface, mouse)
        if self.state.notification_panel_open:
            self.draw_notification_panel(surface, mouse)
        self.draw_open_dropdowns(surface, self.widgets)
        if self.state.modal:
            self.draw_modal(surface, mouse)
        if not self.state.assistant_open and not self.state.modal:
            self.base_surface_cache = surface.copy()
            self.base_surface_cache_key = base_key
            self.base_widgets_cache = list(self.widgets)
            self.base_tables_cache = list(self.tables)
        self.draw_assistant_overlay(surface, mouse)
        if UI_DEBUG_HITBOXES:
            self.draw_debug_hitboxes(surface, mouse)
        self.draw_toasts(surface)

    def add_widget(self, widget, z_index=None, name=None):
        if z_index is not None:
            widget.z_index = z_index
        if name:
            widget.name = name
        self.widgets.append(widget)
        return widget

    def add_table(self, table, z_index=None, name=None):
        if z_index is not None:
            table.z_index = z_index
        if name:
            table.name = name
        self.tables.append(table)
        return table

    def add_assistant_widget(self, widget, z_index=None, name=None):
        if z_index is not None:
            widget.z_index = z_index
        if name:
            widget.name = name
        self.assistant_widgets.append(widget)
        return widget

    def is_focused(self, key):
        return self.state.focused_input_key == key

    def is_select_open(self, key):
        return self.state.open_select_key == key

    def draw_open_dropdowns(self, surface, components):
        mouse = self.state.mouse_pos
        for widget in sorted([item for item in components if isinstance(item, SelectBox) and item.opened], key=lambda item: item.z_index):
            widget.draw_dropdown(surface, self.fonts["small"], mouse)

    def draw_debug_hitboxes(self, surface, mouse):
        font = self.fonts["small"]
        for item in self.widgets + self.tables + self.assistant_widgets + self.modal_widgets:
            rect = getattr(item, "rect", None)
            if not rect:
                continue
            pygame.draw.rect(surface, COLORS["danger"], rect, 1)
            if rect.collidepoint(mouse):
                draw_text(surface, font, getattr(item, "name", item.__class__.__name__), (rect.x + 4, rect.y + 4), COLORS["danger"])

    def toast(self, message, kind="success", ttl=120):
        self.state.toasts.append(Toast(message, kind, ttl))

    def draw_toasts(self, surface):
        if not self.state.toasts:
            return
        toast = self.state.toasts[-1]
        toast.draw(surface, self.fonts["small"])
        toast.ttl -= 1
        self.state.toasts = [item for item in self.state.toasts if item.ttl > 0]

    def draw_login(self, surface, mouse):
        title_font = self.fonts["title"]
        font = self.fonts["normal"]
        rect = pygame.Rect((WIDTH - 420) // 2, 190, 420, 330)
        draw_panel(surface, rect, "AI-ассистент для Спонсора", font, title_font)
        login_key = ("login", "login")
        password_key = ("login", "password")
        login = TextInput(pygame.Rect(rect.x + 32, rect.y + 102, 356, 42), self.state.login, "Логин", self.is_focused(login_key))
        password = PasswordInput(pygame.Rect(rect.x + 32, rect.y + 178, 356, 42), self.state.password, "Пароль", self.is_focused(password_key))
        login.state_key = ("login", "login")
        password.state_key = ("login", "password")
        login.draw(surface, font, mouse)
        password.draw(surface, font, mouse)
        self.add_widget(Button(pygame.Rect(rect.x + 32, rect.y + 242, 356, 44), "Войти", self.try_login)).draw(surface, font, mouse)
        if self.state.login_error:
            draw_text(surface, self.fonts["small"], self.state.login_error, (rect.x + 32, rect.y + 296), COLORS["danger"])
        self.add_widget(login)
        self.add_widget(password)

    def try_login(self):
        from src.auth import login_user

        user = login_user(self.state.login.strip(), self.state.password)
        if user:
            self.state.current_user = user
            self.state.active_tab = MAIN_TAB
            self.state.sections_menu_open = False
            self.state.login_error = ""
        else:
            self.state.login_error = "Неверный логин или пароль"

    def draw_top_bar(self, surface, mouse):
        pygame.draw.rect(surface, COLORS["surface"], (0, 0, WIDTH, 78))
        pygame.draw.line(surface, COLORS["border"], (0, 78), (WIDTH, 78), 1)
        dashboard = self.add_widget(
            Button(pygame.Rect(16, 14, 110, 34), MAIN_TAB, lambda: self.switch_tab(MAIN_TAB), self.state.active_tab == MAIN_TAB),
            name="dashboard_button",
        )
        dashboard.draw(surface, self.fonts["small"], mouse)
        sections = self.add_widget(
            Button(pygame.Rect(138, 14, 126, 34), "Разделы", self.toggle_sections_menu, self.state.sections_menu_open),
            name="sections_button",
        )
        sections.draw(surface, self.fonts["small"], mouse)
        bell_rect = pygame.Rect(WIDTH - 74, 14, 58, 34)
        if self.state.active_tab != MAIN_TAB:
            chip_x = 282
            chip_width = min(280, self.fonts["small"].size(f"Раздел: {self.state.active_tab}")[0] + 22)
            chip_width = min(chip_width, bell_rect.x - chip_x - 18)
            chip = pygame.Rect(chip_x, 14, chip_width, 34)
            pygame.draw.rect(surface, COLORS["table_zebra"], chip, border_radius=17)
            pygame.draw.rect(surface, COLORS["border"], chip, width=1, border_radius=17)
            draw_text(surface, self.fonts["small"], ellipsize(f"Раздел: {self.state.active_tab}", self.fonts["small"], chip.width - 18), (chip.x + 10, chip.y + 9), COLORS["muted"])
        notification_summary = self._notification_summary()
        bell = self.add_widget(NotificationBell(bell_rect, notification_summary["unread_count"], self.toggle_notifications))
        bell.draw(surface, self.fonts["small"], mouse)
        user = self.state.current_user
        draw_text(surface, self.fonts["small"], f"{user.full_name} ({_ru(user.role)})", (18, 53), COLORS["muted"])

    def visible_sections(self):
        user = self.state.current_user
        if not user:
            return []
        return ROLE_SECTIONS.get(user.role, [])

    def draw_sections_menu(self, surface, mouse):
        tabs = self.visible_sections()
        rect = self._sections_menu_rect()
        draw_panel(surface, rect, "Разделы", self.fonts["small"], self.fonts["subtitle"])
        y = rect.y + 52
        for tab in tabs:
            button = self.add_widget(
                Button(pygame.Rect(rect.x + 12, y, rect.width - 24, 30), tab, lambda tab=tab: self.switch_tab(tab), self.state.active_tab == tab),
                z_index=190,
                name=f"section_{tab}",
            )
            button.draw(surface, self.fonts["small"], mouse)
            y += 38

    def switch_tab(self, tab):
        if tab != MAIN_TAB and tab not in self.visible_sections():
            self.toast("Раздел недоступен для вашей роли", "error")
            return
        self.state.active_tab = tab
        self.base_surface_cache = None
        self.state.sections_menu_open = False
        self.state.notification_panel_open = False
        self.state.open_select_key = None
        self.state.focused_input_key = None

    def toggle_notifications(self):
        will_open = not self.state.notification_panel_open
        self.state.notification_panel_open = will_open
        # The notification panel occupies the same right-side area as the chat.
        # Keep one interactive overlay at a time so its controls never sit below
        # the assistant panel and appear unresponsive.
        if will_open:
            self.state.assistant_open = False
            self.state.focused_input_key = None
        self.base_surface_cache = None
        self.state.sections_menu_open = False
        self.state.open_select_key = None

    def toggle_sections_menu(self):
        self.state.sections_menu_open = not self.state.sections_menu_open
        self.base_surface_cache = None
        self.state.notification_panel_open = False
        self.state.open_select_key = None

    def toggle_assistant(self):
        self.state.assistant_open = not self.state.assistant_open
        self.state.open_select_key = None
        self.state.focused_input_key = None

    def close_assistant(self):
        self.state.assistant_open = False
        self.base_surface_cache = None
        self.state.focused_input_key = None

    def draw_assistant_overlay(self, surface, mouse):
        user = self.state.current_user
        if not permissions.can_use_assistant(user):
            return
        has_alerts = self._notification_summary()["has_alerts"]
        if self.state.assistant_open:
            self.draw_assistant_panel(surface, mouse)
            return
        button = self.add_assistant_widget(AssistantFloatingButton(pygame.Rect(WIDTH - 86, HEIGHT - 84, 68, 52), has_alerts, self.toggle_assistant), z_index=320)
        button.draw(surface, self.fonts["subtitle"], mouse)

    def draw_assistant_panel(self, surface, mouse):
        rect = self._assistant_panel_rect()
        AssistantChatPanel(rect).draw(surface, self.fonts, mouse, self.state.assistant_history, self.state.assistant_status, self.state.assistant_context)
        close = self.add_assistant_widget(Button(pygame.Rect(rect.right - 48, rect.y + 14, 32, 32), "X", self.close_assistant, style="ghost"), z_index=340, name="assistant_close")
        close.draw(surface, self.fonts["small"], mouse)

        y = rect.y + 396
        if self.state.assistant_pending_command:
            self.draw_assistant_command_confirmation(surface, mouse, pygame.Rect(rect.x + 16, y, rect.width - 32, 150))
        else:
            for idx, (label, question_text) in enumerate(QUICK_ASSISTANT_QUESTIONS):
                col = idx % 2
                row = idx // 2
                width = 239
                x = rect.x + 16 + col * (width + 10)
                quick = self.add_assistant_widget(
                    Button(pygame.Rect(x, y + row * 54, width, 44), label, lambda question_text=question_text: self.ask_quick_question(question_text), disabled=self.state.assistant_pending),
                    z_index=335,
                    name=f"assistant_quick_{idx}",
                )
                quick.draw(surface, self.fonts["small"], mouse)

        question_key = ("assistant", "question")
        question = self.add_assistant_widget(
            TextInput(pygame.Rect(rect.x + 16, rect.y + 568, 252, 48), self.state.assistant_question, "Введите запрос", self.is_focused(question_key), self.ask_assistant),
            z_index=338,
            name="assistant_question",
        )
        question.state_key = question_key
        question.draw(surface, self.fonts["small"], mouse)
        if UI_DEBUG_FOCUS and self.state.focused_input_key == question_key:
            pygame.draw.rect(surface, COLORS["success"], question.rect, 2, border_radius=6)
            draw_text(surface, self.fonts["small"], "focused: assistant_question", (question.rect.x, question.rect.y - 18), COLORS["success"])

        is_recording = self.state.assistant_voice_recording
        voice = self.add_assistant_widget(
            Button(
                pygame.Rect(rect.x + 280, rect.y + 576, 92, 40),
                "Стоп" if is_recording else "Голос",
                self.start_voice_input,
                disabled=(self.state.assistant_voice_pending and not is_recording) or self.state.assistant_pending,
                style="danger" if is_recording else "secondary",
            ),
            z_index=335,
            name="assistant_voice",
        )
        voice.draw(surface, self.fonts["small"], mouse)
        ask = self.add_assistant_widget(Button(pygame.Rect(rect.right - 128, rect.y + 576, 104, 40), "Спросить", self.ask_assistant, disabled=self.state.assistant_pending or self.state.assistant_voice_pending), z_index=335, name="assistant_ask")
        ask.draw(surface, self.fonts["small"], mouse)

    def draw_assistant_command_confirmation(self, surface, mouse, rect):
        pygame.draw.rect(surface, COLORS["warning_soft"], rect, border_radius=7)
        pygame.draw.rect(surface, COLORS["warning"], rect, width=1, border_radius=7)
        command = self.state.assistant_pending_command
        draw_text(surface, self.fonts["small"], "Требуется подтверждение", (rect.x + 12, rect.y + 10), COLORS["warning"])
        draw_text(surface, self.fonts["small"], ellipsize(command.get("summary", ""), self.fonts["small"], rect.width - 24), (rect.x + 12, rect.y + 36), COLORS["text"])
        confirm = self.add_assistant_widget(Button(pygame.Rect(rect.x + 12, rect.bottom - 44, 190, 32), "Подтвердить выполнение", self.confirm_assistant_command), z_index=340, name="assistant_confirm_command")
        cancel = self.add_assistant_widget(Button(pygame.Rect(rect.x + 216, rect.bottom - 44, 110, 32), "Отмена", self.cancel_assistant_command, style="ghost"), z_index=340, name="assistant_cancel_command")
        confirm.draw(surface, self.fonts["small"], mouse)
        cancel.draw(surface, self.fonts["small"], mouse)

    def ask_quick_question(self, question):
        self.state.assistant_question = question
        self.ask_assistant()

    def _clear_assistant_question(self):
        self.state.assistant_question = ""
        self.state.focused_input_key = None
        for widget in self.assistant_widgets:
            if getattr(widget, "state_key", None) == ("assistant", "question"):
                widget.value = ""
                widget.cursor_pos = 0
                widget.focused = False

    def ask_assistant(self):
        question = (self.state.assistant_question or "").strip()
        if not question:
            self.toast("Введите вопрос", "error")
            return
        if self.state.assistant_pending:
            self.toast("Ассистент уже формирует ответ", "error", ttl=60)
            return
        self.state.assistant_request_id += 1
        request_id = self.state.assistant_request_id
        self.state.assistant_history.append({"role": "user", "text": question})
        self.state.assistant_history.append({"role": "assistant", "text": "Формирую ответ", "pending": True, "request_id": request_id})
        self.state.assistant_pending = True
        self.state.assistant_status = ""
        self._clear_assistant_question()
        threading.Thread(target=self._run_assistant_request, args=(request_id, self.state.current_user, question), daemon=True).start()

    def start_voice_input(self):
        if self.state.assistant_voice_recording and self.voice_stop_event:
            self.voice_stop_event.set()
            self.state.assistant_voice_recording = False
            self.state.assistant_status = "Распознаю запрос..."
            return
        if self.state.assistant_voice_pending or self.state.assistant_pending:
            return
        self.state.assistant_voice_pending = True
        self.state.assistant_voice_recording = True
        self.state.assistant_status = "Слушаю вас... Нажмите «Стоп»"
        self.voice_stop_event = threading.Event()
        threading.Thread(target=self._run_voice_input, args=(self.voice_stop_event,), daemon=True).start()

    def _run_voice_input(self, stop_event):
        try:
            self.voice_results.put({
                "text": transcribe_microphone(
                    stop_event=stop_event,
                    on_recording_complete=lambda: self.voice_results.put({"phase": "transcribing"}),
                )
            })
        except Exception as exc:
            self.voice_results.put({"error": str(exc)})

    def poll_voice_results(self):
        while True:
            try:
                item = self.voice_results.get_nowait()
            except Empty:
                return
            if item.get("phase") == "transcribing":
                self.state.assistant_voice_recording = False
                self.state.assistant_status = "Распознаю запрос..."
                continue
            self.state.assistant_voice_pending = False
            self.state.assistant_voice_recording = False
            self.voice_stop_event = None
            self.state.assistant_status = ""
            if item.get("error"):
                self.toast(item["error"], "error", ttl=8)
                continue
            self.state.assistant_question = item.get("text", "")
            self.state.focused_input_key = ("assistant", "question")
            self.toast("Голосовой запрос распознан")

    def _run_assistant_request(self, request_id, user, question):
        try:
            result = assistant_service.answer_question(user, question)
            self.assistant_results.put({"request_id": request_id, "result": result})
        except Exception as exc:
            self.assistant_results.put({"request_id": request_id, "error": str(exc)})

    def poll_assistant_results(self):
        while True:
            try:
                item = self.assistant_results.get_nowait()
            except Empty:
                return
            request_id = item.get("request_id")
            result = item.get("result") or {}
            answer = result.get("answer") or item.get("error") or "GigaChat не ответил"
            replaced = False
            for message in reversed(self.state.assistant_history):
                if message.get("pending") and message.get("request_id") == request_id:
                    message["text"] = answer
                    message["pending"] = False
                    if result.get("status") == "command_pending" and result.get("command"):
                        message["command_pending"] = True
                    replaced = True
                    break
            if result.get("status") == "command_pending" and result.get("command"):
                self.state.assistant_pending_command = result["command"]
            if not replaced:
                self.state.assistant_history.append({"role": "assistant", "text": answer})
            if request_id == self.state.assistant_request_id:
                self.state.assistant_pending = False
                self.state.assistant_status = ""
            if result.get("status") == "error" or item.get("error"):
                self.toast("GigaChat не ответил", "error", ttl=60)

    def confirm_assistant_command(self):
        command = self.state.assistant_pending_command
        if not command:
            return
        try:
            answer = assistant_service.execute_task_command(self.state.current_user, command)
            self.state.assistant_history.append({"role": "assistant", "text": answer})
            self.toast("Команда выполнена")
        except Exception as exc:
            self.state.assistant_history.append({"role": "assistant", "text": f"Не удалось выполнить команду: {exc}"})
            self.toast("Команда не выполнена", "error")
        finally:
            self.state.assistant_pending_command = {}
            self.base_surface_cache = None

    def cancel_assistant_command(self):
        self.state.assistant_pending_command = {}
        self.state.assistant_history.append({"role": "assistant", "text": "Команда отменена. Данные не изменены."})

    def data(self):
        cache_key = getattr(self.state.current_user, "id", None)
        now = monotonic()
        if self.data_cache_key == cache_key and self.data_cache is not None and now - self.data_cache_at < 5.0:
            return self.data_cache
        user = self.state.current_user
        clients = repositories.get_clients_for_user(user)
        projects = repositories.get_projects_for_user(user)
        tasks = repositories.get_tasks_for_user(user)
        deals = repositories.get_deals_for_user(user)
        meetings = repositories.get_meetings_for_user(user)
        users = repositories.get_users()
        client_by_id = {c.id: c for c in clients}
        project_by_id = {p.id: p for p in projects}
        user_by_id = {u.id: u for u in users}
        payload = (clients, projects, tasks, deals, meetings, [], users, client_by_id, project_by_id, user_by_id)
        self.data_cache_key = cache_key
        self.data_cache = payload
        self.data_cache_at = now
        return payload

    def _invalidate_runtime_cache(self):
        self.base_surface_cache = None
        self.base_widgets_cache = []
        self.base_tables_cache = []
        self.data_cache_key = None
        self.data_cache = None
        self.data_cache_at = 0.0
        self.risk_cache = {}
        self.analytics_cache = {}
        self.notification_summary_cache = None
        self.notification_summary_at = 0.0

    def _client_risk(self, client_id):
        cache_key = (getattr(self.state.current_user, "id", None), client_id)
        now = monotonic()
        cached = self.risk_cache.get(cache_key)
        if cached and now - cached["at"] < 30.0:
            return cached["value"]
        value = calculate_client_risk(self.state.current_user, client_id)
        self.risk_cache[cache_key] = {"value": value, "at": now}
        return value

    def _dashboard_analytics(self, clients, tasks, deals, meetings):
        user_id = getattr(self.state.current_user, "id", None)
        cache_key = (
            user_id,
            tuple(client.id for client in clients),
            len(tasks),
            len(deals),
            len(meetings),
        )
        now = monotonic()
        cached = self.analytics_cache.get(cache_key)
        if cached and now - cached["at"] < 30.0:
            return cached["value"]
        value = build_dashboard_analytics(clients, tasks, deals, meetings, days=14)
        self.analytics_cache = {cache_key: {"value": value, "at": now}}
        return value

    def _notification_summary(self):
        user_id = getattr(self.state.current_user, "id", None)
        if not user_id:
            return {"unread_count": 0, "has_alerts": False}
        now = monotonic()
        cached = self.notification_summary_cache
        if cached and cached["key"] == user_id and now - self.notification_summary_at < 5.0:
            return cached["value"]
        value = repositories.get_notification_summary(self.state.current_user)
        self.notification_summary_cache = {"key": user_id, "value": value}
        self.notification_summary_at = now
        return value

    def search_value(self, key, rect, placeholder):
        value = self.state.filters.get(key, "")
        state_key = ("filters", key)
        widget = self.add_widget(SearchBox(rect, value, placeholder, self.is_focused(state_key)), name=key)
        widget.state_key = state_key
        widget.draw(pygame.display.get_surface(), self.fonts["small"], self.state.mouse_pos)
        self.state.filters[key] = widget.value
        return widget.value

    def filter_select(self, key, rect, options):
        value = self.state.filters.get(key, "Все")
        if value not in options:
            value = "Все"
        state_key = ("filters", key)
        widget = self.add_widget(SelectBox(rect, options, value, self.is_select_open(state_key), on_change=lambda val, key=key: self.state.filters.__setitem__(key, val)), name=key)
        widget.state_key = state_key
        widget.draw(pygame.display.get_surface(), self.fonts["small"], self.state.mouse_pos)
        return value

    def draw_kpi(self, surface, rect, label, value, color=COLORS["primary"]):
        draw_panel(surface, rect)
        draw_text(surface, self.fonts["small"], label, (rect.x + 14, rect.y + 12), COLORS["muted"])
        draw_text(surface, self.fonts["title"], value, (rect.x + 14, rect.y + 36), color)

    def draw_dashboard(self, surface, mouse):
        if self.state.current_user.role == "manager":
            self.draw_manager_dashboard(surface, mouse)
            return

        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        today = date.today()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)
        upcoming_limit = datetime.combine(today + timedelta(days=7), time.max)
        overdue = [t for t in tasks if t.status == "overdue" or (t.due_date and t.due_date < today and t.status not in {"done", "cancelled"})]
        no_offer = [d for d in deals if not d.commercial_offer_exists]
        soon_meetings = [m for m in meetings if m.status == "planned" and m.meeting_datetime <= upcoming_limit]
        meetings_today = [m for m in meetings if m.status == "planned" and today_start <= m.meeting_datetime <= today_end]

        risk_rows = []
        risk_infos = []
        for client in clients:
            try:
                risk = self._client_risk(client.id)
            except Exception:
                continue
            risk_infos.append((client, risk))
            if risk["risk_level"] in {"high", "medium"}:
                risk_rows.append({
                    "id": client.id,
                    "client": client.name,
                    "level": "высокий" if risk["risk_level"] == "high" else "средний",
                    "health": client.health_score,
                    "risk": risk["risk_score_local"],
                    "reason": risk["risk_reasons"][0] if risk["risk_reasons"] else "нет явной причины",
                })
        risk_rows = sorted(risk_rows, key=lambda item: item["risk"], reverse=True)

        user_name = self.state.current_user.full_name
        draw_text(surface, self.fonts["title"], f"Добрый день, {user_name}", (18, 96))
        summary = f"Сегодня требуют внимания: {len(risk_rows)} клиентов, {len(overdue)} задач, {len(meetings_today)} встреч."
        draw_text(surface, self.fonts["normal"], summary, (18, 126), COLORS["muted"])
        if self.state.current_user.role == "admin":
            self.draw_button(surface, pygame.Rect(964, 96, 136, 30), "Проверки", self.run_background_checks)
            self.draw_button(surface, pygame.Rect(1114, 96, 148, 30), "Сводка дня", self.generate_daily_digest)

        analytics = self._dashboard_analytics(clients, tasks, deals, meetings)
        high_risk_count = len([item for item in risk_infos if item[1].get("risk_level") == "high"])
        kpis = [
            ("Клиенты в фокусе", len(risk_rows), COLORS["primary"]),
            ("Высокие риски", high_risk_count, COLORS["danger"] if high_risk_count else COLORS["success"]),
            ("Просроченные задачи", len(overdue), COLORS["danger"] if overdue else COLORS["success"]),
            ("Сделки без КП", len(no_offer), COLORS["warning"] if no_offer else COLORS["success"]),
        ]
        x = 18
        for label, value, color in kpis:
            self.draw_kpi(surface, pygame.Rect(x, 154, 296, 78), label, str(value), color)
            x += 312

        attention = []
        for task in tasks:
            if task in overdue or task.status == "blocked":
                client = client_by_id.get(task.client_id)
                owner = user_by_id.get(task.assignee_user_id)
                reason = "просрочена" if task in overdue else "заблокирована"
                attention.append({"id": task.id, "tab": "Задачи", "select_key": "task", "type": "Задача", "client": client.name if client else "", "reason": reason, "action": task.title, "deadline": _fmt(task.due_date), "owner": owner.full_name if owner else ""})
        for deal in no_offer:
            client = client_by_id.get(deal.client_id)
            attention.append({"id": deal.id, "tab": "Сделки", "select_key": "deal", "type": "Сделка", "client": client.name if client else "", "reason": "нет КП", "action": deal.name, "deadline": _fmt(deal.last_activity_date), "owner": ""})
        for client, risk in risk_infos:
            if risk["risk_level"] == "high":
                attention.append({"id": client.id, "tab": "Клиенты", "select_key": "client", "type": "Клиент", "client": client.name, "reason": risk["risk_reasons"][0] if risk["risk_reasons"] else "высокий риск", "action": "Назначить разбор", "deadline": _fmt(client.next_contact_due), "owner": ""})
        try:
            for item in get_clients_with_contact_policy_violations()[:3]:
                client = item["client"]
                attention.append({"id": client.id, "tab": "Клиенты", "select_key": "client", "type": "Контакт", "client": client.name, "reason": "контактная политика", "action": item["check"]["message"], "deadline": _fmt(client.next_contact_due), "owner": ""})
        except Exception:
            pass
        attention = attention[:DEMO_DASHBOARD_LIMIT]

        meeting_cards = []
        for meeting in sorted(soon_meetings, key=lambda item: item.meeting_datetime)[:3]:
            client = client_by_id.get(meeting.client_id)
            day = meeting.meeting_datetime.date()
            when = "сегодня" if day == today else "завтра" if day == today + timedelta(days=1) else meeting.meeting_datetime.strftime("%d.%m")
            meeting_cards.append({"id": meeting.id, "when": when, "time": meeting.meeting_datetime.strftime("%H:%M"), "client": client.name if client else "", "title": meeting.title})
        self.draw_portfolio_analytics(surface, mouse, pygame.Rect(18, 260, 1244, 176), analytics)
        self.draw_attention_cards(surface, pygame.Rect(18, 454, 610, 304), attention)
        self.draw_meeting_cards(surface, pygame.Rect(646, 454, 300, 304), meeting_cards)
        self.draw_recommendations(surface, pygame.Rect(964, 454, 298, 304), risk_rows, overdue, no_offer, clients)

    def draw_attention_cards(self, surface, rect, items):
        draw_panel(surface, rect, "Что требует внимания", self.fonts["small"], self.fonts["subtitle"])
        if not items:
            draw_text(surface, self.fonts["normal"], "Критичных действий на сегодня нет", (rect.x + 18, rect.y + 64), COLORS["muted"])
            return
        y = rect.y + 56
        for item in items[:DEMO_DASHBOARD_LIMIT]:
            card = pygame.Rect(rect.x + 14, y, rect.width - 28, 48)
            pygame.draw.rect(surface, COLORS["table_zebra"], card, border_radius=7)
            pygame.draw.rect(surface, COLORS["border"], card, width=1, border_radius=7)
            button_rect = pygame.Rect(card.right - 86, card.y + 10, 74, 28)
            content_right = button_rect.x - 10
            badge_color = COLORS["danger"] if item["type"] in {"Задача", "Клиент"} else COLORS["warning"]
            draw_text(surface, self.fonts["small"], item["type"], (card.x + 10, card.y + 6), badge_color)
            draw_text(surface, self.fonts["small"], ellipsize(item.get("client", ""), self.fonts["small"], max(80, content_right - (card.x + 84))), (card.x + 84, card.y + 6))
            reason_text = _dashboard_reason_label(item.get("reason", ""))
            reason_width = self.fonts["small"].size(reason_text)[0]
            reason_x = max(card.x + 250, content_right - reason_width)
            action_width = max(90, reason_x - (card.x + 10) - 14)
            draw_text(surface, self.fonts["small"], ellipsize(item.get("action", ""), self.fonts["small"], action_width), (card.x + 10, card.y + 26), COLORS["text"])
            draw_text(surface, self.fonts["small"], reason_text, (reason_x, card.y + 26), COLORS["muted"])
            self.draw_button(surface, button_rect, "Открыть", lambda item=item: self.open_attention_item(item), z_index=30)
            y += 54

    def draw_risk_cards(self, surface, rect, rows):
        draw_panel(surface, rect, "Риски по клиентам", self.fonts["small"], self.fonts["subtitle"])
        if not rows:
            draw_text(surface, self.fonts["normal"], "Нет клиентов в зоне риска", (rect.x + 16, rect.y + 64), COLORS["muted"])
            return
        y = rect.y + 56
        for row in rows[:DEMO_DASHBOARD_LIMIT]:
            card = pygame.Rect(rect.x + 12, y, rect.width - 24, 52)
            pygame.draw.rect(surface, COLORS["table_zebra"], card, border_radius=7)
            pygame.draw.rect(surface, COLORS["border"], card, width=1, border_radius=7)
            button_rect = pygame.Rect(card.right - 86, card.y + 12, 74, 28)
            content_right = button_rect.x - 10
            color = COLORS["danger"] if row["level"] == "высокий" else COLORS["warning"]
            level_width = self.fonts["small"].size(row["level"])[0]
            level_x = max(card.x + 120, content_right - level_width)
            draw_text(surface, self.fonts["small"], ellipsize(row["client"], self.fonts["small"], max(80, level_x - (card.x + 10) - 10)), (card.x + 10, card.y + 8))
            draw_text(surface, self.fonts["small"], row["level"], (level_x, card.y + 8), color)
            draw_text(surface, self.fonts["small"], f"Оценка {row['health']}", (card.x + 10, card.y + 29), COLORS["muted"])
            draw_text(surface, self.fonts["small"], _dashboard_reason_label(row["reason"]), (card.x + 92, card.y + 29), COLORS["muted"])
            self.draw_button(surface, button_rect, "Открыть", lambda row=row: self.open_client_from_dashboard(row["id"]), z_index=30)
            y += 58

    def draw_meeting_cards(self, surface, rect, rows):
        draw_panel(surface, rect, "Ближайшие встречи", self.fonts["small"], self.fonts["subtitle"])
        if not rows:
            draw_text(surface, self.fonts["normal"], "Нет встреч", (rect.x + 16, rect.y + 64), COLORS["muted"])
            return
        y = rect.y + 58
        for row in rows[:3]:
            card = pygame.Rect(rect.x + 12, y, rect.width - 24, 72)
            pygame.draw.rect(surface, COLORS["table_zebra"], card, border_radius=7)
            pygame.draw.rect(surface, COLORS["border"], card, width=1, border_radius=7)
            button_rect = pygame.Rect(card.right - 86, card.y + 22, 74, 28)
            content_right = button_rect.x - 12
            draw_text(surface, self.fonts["subtitle"], row["time"], (card.x + 10, card.y + 8), COLORS["primary"])
            when_text = ellipsize(row["when"], self.fonts["small"], 56)
            when_width = self.fonts["small"].size(when_text)[0]
            draw_text(surface, self.fonts["small"], when_text, (content_right - when_width, card.y + 11), COLORS["muted"])
            text_width = max(70, content_right - (card.x + 10))
            draw_text(surface, self.fonts["small"], ellipsize(row["client"], self.fonts["small"], text_width), (card.x + 10, card.y + 34))
            draw_text(surface, self.fonts["small"], ellipsize(row["title"], self.fonts["small"], text_width), (card.x + 10, card.y + 52), COLORS["muted"])
            self.draw_button(surface, button_rect, "Открыть", lambda row=row: self.open_meeting_from_dashboard(row["id"]), z_index=30)
            y += 78

    def draw_portfolio_analytics(self, surface, mouse, rect, analytics):
        draw_text(surface, self.fonts["subtitle"], "Аналитика портфеля", (rect.x, rect.y - 28))
        analytics_subtitle = ellipsize(
            "Три компактных графика по ключевым отклонениям",
            self.fonts["small"],
            520,
        )
        draw_text(surface, self.fonts["small"], analytics_subtitle, (rect.x + 268, rect.y - 24), COLORS["muted"])
        self.draw_line_chart_card(
            surface,
            mouse,
            pygame.Rect(rect.x, rect.y, 520, rect.height),
            "Динамика рисков",
            "Клиенты со средним и высоким риском за 14 дней",
            analytics.get("risk_trend", []),
        )
        self.draw_horizontal_bar_chart_card(
            surface,
            mouse,
            pygame.Rect(rect.x + 538, rect.y, 344, rect.height),
            "Задачи по статусам",
            "Новые, в работе, просроченные и выполненные",
            analytics.get("task_status_distribution", []),
            {
                "open": COLORS["secondary"],
                "in_progress": COLORS["warning"],
                "overdue": COLORS["danger"],
                "done": COLORS["success"],
            },
        )
        self.draw_vertical_bar_chart_card(
            surface,
            mouse,
            pygame.Rect(rect.x + 900, rect.y, 344, rect.height),
            "Сделки по стадиям",
            "Структура воронки по закреплённым клиентам",
            analytics.get("deal_stage_distribution", []),
            [COLORS["secondary"], COLORS["primary"], COLORS["warning"], COLORS["danger"], COLORS["success"], COLORS["muted"]],
        )

    def draw_line_chart_card(self, surface, mouse, rect, title, subtitle, points):
        draw_panel(surface, rect, title, self.fonts["small"], self.fonts["subtitle"])
        draw_text(surface, self.fonts["small"], ellipsize(subtitle, self.fonts["small"], rect.width - 32), (rect.x + 16, rect.y + 56), COLORS["muted"])
        if not points:
            draw_text(surface, self.fonts["small"], "Недостаточно данных для графика", (rect.x + 16, rect.y + 84), COLORS["muted"])
            return
        chart_rect = pygame.Rect(rect.x + 16, rect.y + 76, rect.width - 32, rect.height - 92)
        values = [point["value"] for point in points]
        max_value = max(values) if max(values) > 0 else 1
        pygame.draw.line(surface, COLORS["border"], (chart_rect.x, chart_rect.bottom), (chart_rect.right, chart_rect.bottom), 1)
        prev_pos = None
        for idx, point in enumerate(points):
            ratio = 0 if len(points) == 1 else idx / (len(points) - 1)
            x = chart_rect.x + int(chart_rect.width * ratio)
            y = chart_rect.bottom - int((chart_rect.height - 18) * point["value"] / max_value)
            pos = (x, y)
            if prev_pos:
                pygame.draw.line(surface, COLORS["primary"], prev_pos, pos, 3)
            hover = abs(mouse[0] - x) <= 10 and abs(mouse[1] - y) <= 10
            pygame.draw.circle(surface, COLORS["surface"], pos, 7 if hover else 6)
            pygame.draw.circle(surface, COLORS["primary_hover"] if hover else COLORS["primary"], pos, 4 if hover else 3)
            if hover or idx in {0, len(points) - 1, len(points) // 2}:
                draw_text(surface, self.fonts["small"], str(point["value"]), (x - 6, y - 20), COLORS["primary_dark"])
            if idx in {0, len(points) // 2, len(points) - 1}:
                label = point["label"]
                label_x = max(chart_rect.x, min(x - self.fonts["small"].size(label)[0] // 2, chart_rect.right - self.fonts["small"].size(label)[0]))
                draw_text(surface, self.fonts["small"], label, (label_x, chart_rect.bottom + 2), COLORS["muted"])
            prev_pos = pos

    def draw_horizontal_bar_chart_card(self, surface, mouse, rect, title, subtitle, items, color_by_key):
        draw_panel(surface, rect, title, self.fonts["small"], self.fonts["subtitle"])
        draw_text(surface, self.fonts["small"], ellipsize(subtitle, self.fonts["small"], rect.width - 32), (rect.x + 16, rect.y + 56), COLORS["muted"])
        if not items:
            draw_text(surface, self.fonts["small"], "Недостаточно данных для графика", (rect.x + 16, rect.y + 84), COLORS["muted"])
            return
        max_value = max([item["value"] for item in items] or [0]) or 1
        y = rect.y + 80
        for item in items:
            label_w = 124
            draw_text(surface, self.fonts["small"], item["label"], (rect.x + 16, y), COLORS["text"])
            track = pygame.Rect(rect.x + 150, y + 3, rect.width - 212, 12)
            fill_w = int(track.width * item["value"] / max_value) if item["value"] else 0
            fill = pygame.Rect(track.x, track.y, max(6, fill_w) if item["value"] else 0, track.height)
            hover = track.collidepoint(mouse)
            pygame.draw.rect(surface, COLORS["surface_alt"], track, border_radius=6)
            if item["value"]:
                pygame.draw.rect(surface, color_by_key.get(item["key"], COLORS["primary"]), fill, border_radius=6)
            if hover:
                pygame.draw.rect(surface, COLORS["border_strong"], track, width=1, border_radius=6)
            draw_text(surface, self.fonts["small"], str(item["value"]), (rect.right - 38, y), COLORS["text"])
            y += 18

    def draw_vertical_bar_chart_card(self, surface, mouse, rect, title, subtitle, items, palette):
        draw_panel(surface, rect, title, self.fonts["small"], self.fonts["subtitle"])
        draw_text(surface, self.fonts["small"], ellipsize(subtitle, self.fonts["small"], rect.width - 32), (rect.x + 16, rect.y + 56), COLORS["muted"])
        if not items or not any(item["value"] for item in items):
            draw_text(surface, self.fonts["small"], "Недостаточно данных для графика", (rect.x + 16, rect.y + 84), COLORS["muted"])
            return
        chart_rect = pygame.Rect(rect.x + 18, rect.y + 76, rect.width - 36, rect.height - 92)
        pygame.draw.line(surface, COLORS["border"], (chart_rect.x, chart_rect.bottom), (chart_rect.right, chart_rect.bottom), 1)
        max_value = max(item["value"] for item in items) or 1
        slot_w = max(44, chart_rect.width // max(1, len(items)))
        for idx, item in enumerate(items):
            bar_w = min(42, slot_w - 18)
            x = chart_rect.x + idx * slot_w + (slot_w - bar_w) // 2
            h = int((chart_rect.height - 18) * item["value"] / max_value)
            bar = pygame.Rect(x, chart_rect.bottom - max(h, 2), bar_w, max(h, 2))
            hover = bar.collidepoint(mouse)
            color = palette[idx % len(palette)]
            pygame.draw.rect(surface, color, bar, border_radius=6)
            if hover:
                pygame.draw.rect(surface, COLORS["border_strong"], bar, width=1, border_radius=6)
            draw_text(surface, self.fonts["small"], str(item["value"]), (x + 8, bar.y - 18), COLORS["text"])
            label = ellipsize(item["label"], self.fonts["small"], max(24, slot_w - 4))
            label_width = self.fonts["small"].size(label)[0]
            label_x = chart_rect.x + idx * slot_w + max(0, (slot_w - label_width) // 2)
            draw_text(surface, self.fonts["small"], label, (label_x, chart_rect.bottom + 2), COLORS["muted"])

    def draw_score_distribution_card(self, surface, mouse, rect, title, subtitle, items):
        draw_panel(surface, rect, title, self.fonts["small"], self.fonts["subtitle"])
        draw_text(surface, self.fonts["small"], subtitle, (rect.x + 16, rect.y + 56), COLORS["muted"])
        if not items:
            draw_text(surface, self.fonts["small"], "Недостаточно данных для графика", (rect.x + 16, rect.y + 84), COLORS["muted"])
            return
        colors = [COLORS["success"], COLORS["warning"], COLORS["danger"]]
        y = rect.y + 80
        for idx, item in enumerate(items):
            color = colors[idx % len(colors)]
            label_rect = pygame.Rect(rect.x + 16, y, 88, 18)
            track = pygame.Rect(rect.x + 118, y + 3, rect.width - 188, 12)
            fill = pygame.Rect(track.x, track.y, int(track.width * item["share"] / 100), track.height)
            hover = track.collidepoint(mouse)
            draw_text(surface, self.fonts["small"], item["label"], (label_rect.x, label_rect.y), COLORS["text"])
            pygame.draw.rect(surface, COLORS["surface_alt"], track, border_radius=6)
            if item["share"] > 0:
                pygame.draw.rect(surface, color, fill, border_radius=6)
            if hover:
                pygame.draw.rect(surface, COLORS["border_strong"], track, width=1, border_radius=6)
            draw_text(surface, self.fonts["small"], f"{item['value']} / {item['share']}%", (rect.right - 88, y), COLORS["muted"])
            y += 18

    def open_attention_item(self, item):
        self.state.selected[item["select_key"]] = item["id"]
        self.switch_tab(item["tab"])

    def ask_attention_details(self):
        self.state.assistant_open = True
        self.state.assistant_question = "Объясни подробнее, что требует внимания сегодня"
        self.state.focused_input_key = None
        self.ask_assistant()

    def draw_manager_dashboard(self, surface, mouse):
        tasks = repositories.get_tasks_for_user(self.state.current_user)
        messages = repositories.get_messages_for_user(self.state.current_user)
        notification_summary = self._notification_summary()
        today = date.today()
        overdue = [t for t in tasks if t.status == "overdue" or (t.due_date and t.due_date < today and t.status not in {"done", "cancelled"})]
        unread_messages = [m for m in messages if m.receiver_user_id == self.state.current_user.id and m.status == "unread"]
        kpis = [
            ("Мои задачи", len(tasks), COLORS["primary"]),
            ("Просрочено", len(overdue), COLORS["danger"] if overdue else COLORS["success"]),
            ("Непрочитанные сообщения", len(unread_messages), COLORS["danger"] if unread_messages else COLORS["success"]),
            ("Уведомления", notification_summary["unread_count"], COLORS["warning"] if notification_summary["unread_count"] else COLORS["success"]),
        ]
        x = 18
        for label, value, color in kpis:
            self.draw_kpi(surface, pygame.Rect(x, 96, 286, 78), label, str(value), color)
            x += 316
        rows = [{"id": t.id, "title": t.title, "due": _fmt(t.due_date), "status": _ru(t.status), "priority": _ru(t.priority)} for t in tasks[:10]]
        self.draw_table_block(surface, "Мои задачи", pygame.Rect(18, 210, 604, 360), [
            {"key": "title", "title": "Задача", "width": 260},
            {"key": "due", "title": "Срок", "width": 110},
            {"key": "status", "title": "Статус", "width": 120},
            {"key": "priority", "title": "Приоритет", "width": 114},
        ], rows, "dash_manager_tasks", lambda row: self.open_task_from_dashboard(row["id"]))
        self.draw_button(surface, pygame.Rect(500, 580, 122, 28), "Подробнее", lambda: self.switch_tab("Задачи"))
        message_rows = [{"id": m.id, "title": m.title, "body": m.body, "status": _ru(m.status), "created": _fmt(m.created_at)} for m in messages[:8]]
        self.draw_table_block(surface, "Сообщения", pygame.Rect(656, 210, 606, 360), [
            {"key": "title", "title": "Тема", "width": 180},
            {"key": "body", "title": "Сообщение", "width": 250},
            {"key": "status", "title": "Статус", "width": 80},
            {"key": "created", "title": "Дата", "width": 96},
        ], message_rows, "dash_manager_messages")
        self.draw_button(surface, pygame.Rect(1140, 580, 122, 28), "Подробнее", lambda: self.switch_tab("Сообщения"))

    def open_client_from_dashboard(self, client_id):
        self.state.selected["client"] = client_id
        self.switch_tab("Клиенты")

    def open_task_from_dashboard(self, task_id):
        self.state.selected["task"] = task_id
        self.switch_tab("Задачи")

    def open_meeting_from_dashboard(self, meeting_id):
        self.state.selected["meeting"] = meeting_id
        self.switch_tab("Календарь")

    def draw_bar_summary(self, surface, rect, items, title):
        draw_panel(surface, rect)
        draw_text(surface, self.fonts["small"], title, (rect.x + 12, rect.y + 10), COLORS["muted"])
        max_value = max([value for _, value, _ in items] or [1]) or 1
        bar_w = max(36, (rect.width - 44) // max(1, len(items)))
        for idx, (label, value, color) in enumerate(items):
            x = rect.x + 18 + idx * bar_w
            h = int((rect.height - 58) * value / max_value)
            bar = pygame.Rect(x, rect.bottom - 28 - h, bar_w - 18, h or 2)
            pygame.draw.rect(surface, color, bar, border_radius=4)
            draw_text(surface, self.fonts["small"], str(value), (x, rect.bottom - 48 - h), color)
            draw_text(surface, self.fonts["small"], label, (x, rect.bottom - 22), COLORS["muted"])

    def draw_plan_fact_summary(self, surface, rect, rows, title):
        draw_panel(surface, rect)
        draw_text(surface, self.fonts["small"], title, (rect.x + 12, rect.y + 10), COLORS["muted"])
        if not rows:
            draw_text(surface, self.fonts["small"], "Нет данных", (rect.x + 18, rect.y + 48), COLORS["muted"])
            return
        max_value = max([max(plan or 0, fact or 0) for _, plan, fact in rows] or [1]) or 1
        y = rect.y + 36
        for name, plan, fact in rows[:3]:
            label_width = max(56, min(120, rect.width // 2 - 18))
            label = ellipsize(name, self.fonts["small"], label_width)
            draw_text(surface, self.fonts["small"], label, (rect.x + 12, y), COLORS["text"])
            base_x = rect.x + label_width + 24
            available_w = max(22, rect.right - base_x - 14)
            plan_w = int(available_w * (plan or 0) / max_value)
            fact_w = int(available_w * (fact or 0) / max_value)
            pygame.draw.rect(surface, COLORS["selected"], pygame.Rect(base_x, y + 2, plan_w, 7), border_radius=3)
            pygame.draw.rect(surface, COLORS["success"], pygame.Rect(base_x, y + 12, fact_w, 7), border_radius=3)
            y += 24

    def draw_recommendations(self, surface, rect, risk_rows, overdue, no_offer, clients):
        draw_panel(surface, rect, "Рекомендации AI", self.fonts["small"], self.fonts["subtitle"])
        items = []
        if overdue:
            items.append("Разобрать просроченные задачи высокого приоритета")
        if no_offer:
            items.append("Проверить сделки без КП")
        stale = [c for c in clients if c.next_contact_due and c.next_contact_due < date.today()]
        if stale:
            items.append("Назначить встречи клиентам без контакта")
        if risk_rows:
            items.append("Начать с клиентов с высоким риском")
        if len(items) < 3:
            items.append("Посмотреть клиентов с падением факта ниже плана")
        latest_digest = daily_digest_service.get_latest_daily_digest()
        if latest_digest:
            items.insert(0, "Ежедневная сводка: " + ellipsize(latest_digest.digest_text.splitlines()[0], self.fonts["small"], 330))
        y = rect.y + 52
        for item in items[:3]:
            draw_text(surface, self.fonts["small"], "•", (rect.x + 16, y), COLORS["primary"])
            draw_text(surface, self.fonts["small"], ellipsize(item, self.fonts["small"], rect.width - 150), (rect.x + 34, y))
            y += 26
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 44, 132, 30), "Спросить AI", self.ask_attention_details, z_index=30)

    def draw_table_block(self, surface, title, rect, columns, rows, key, on_row_click=None, selected_id=None):
        rows = rows[:DEMO_TABLE_LIMIT]
        draw_text(surface, self.fonts["subtitle"], title, (rect.x, rect.y - 30))
        table = ScrollableTable(rect, columns, rows, self.state.scrolls.get(key, 0), selected_id or self.state.selected.get(key), on_row_click)
        table.name = key
        table.draw(surface, self.fonts["small"], self.state.mouse_pos)
        self.state.scrolls[key] = table.scroll_offset
        self.add_table(table)
        return table

    def draw_toolbar_label(self, surface, text, x, y):
        draw_text(surface, self.fonts["small"], text, (x, y - 18), COLORS["muted"])

    def draw_clients(self, surface, mouse):
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        q = self.draw_input(surface, "client_search", pygame.Rect(18, 110, 230, 34), "Поиск клиента")
        priority = self.draw_select(surface, "client_priority", pygame.Rect(260, 110, 150, 34), _ru_options(sorted({c.priority for c in clients if c.priority}), PRIORITY_LABELS))
        status = self.draw_select(surface, "client_status", pygame.Rect(422, 110, 190, 34), _ru_options(sorted({c.relationship_status for c in clients if c.relationship_status}), STATUS_LABELS))
        priority_code = _code_from_ru(priority, PRIORITY_LABELS)
        status_code = _code_from_ru(status, STATUS_LABELS)
        can_admin = self.state.current_user.role == "admin"
        self.draw_button(surface, pygame.Rect(625, 110, 150, 34), "Создать клиента", self.open_client_modal, disabled=not can_admin)

        rows = []
        for c in clients:
            row = {"id": c.id, "name": c.name, "industry": c.industry, "segment": c.segment, "priority": _ru(c.priority), "health": c.health_score, "status": _ru(c.relationship_status), "last": _fmt(c.last_contact_date), "next": _fmt(c.next_contact_due)}
            if _contains(row, q) and (priority == "Все" or c.priority == priority_code) and (status == "Все" or c.relationship_status == status_code):
                rows.append(row)
        rows = sorted(rows, key=lambda row: (int(row.get("health") or 100), row.get("name", "")))
        self.draw_table_block(surface, "Клиенты", pygame.Rect(18, 175, 820, 580), [
            {"key": "name", "title": "Клиент", "width": 180},
            {"key": "industry", "title": "Отрасль", "width": 130},
            {"key": "segment", "title": "Сегмент", "width": 100},
            {"key": "priority", "title": "Приоритет", "width": 88},
            {"key": "health", "title": "Оценка", "width": 70},
            {"key": "status", "title": "Статус", "width": 120},
            {"key": "last", "title": "Последний", "width": 100},
        ], rows, "clients", lambda row: self.select("client", row["id"]), self.state.selected.get("client"))
        self.draw_client_detail(surface, pygame.Rect(858, 110, 404, 645), client_by_id.get(self.state.selected.get("client")), projects, tasks, deals, meetings)

    def draw_client_detail(self, surface, rect, client, projects, tasks, deals, meetings):
        draw_panel(surface, rect, f"Клиент: {client.name}" if client else "Клиент", self.fonts["small"], self.fonts["subtitle"])
        if not client:
            draw_text(surface, self.fonts["normal"], "Выберите клиента в таблице", (rect.x + 16, rect.y + 66), COLORS["muted"])
            return

        client_projects = [p for p in projects if p.client_id == client.id]
        client_tasks = [t for t in tasks if t.client_id == client.id or (t.project_id and any(p.id == t.project_id for p in client_projects))]
        client_deals = [d for d in deals if d.client_id == client.id]
        client_meetings = [m for m in meetings if m.client_id == client.id]
        indicators = repositories.get_indicators_by_client(client.id)
        business_dates = repositories.get_business_dates_by_client(client.id)
        project_ids = {p.id for p in client_projects}
        team = []
        for project in client_projects:
            team.extend(repositories.get_project_team(project.id))
        next_meeting = next((m for m in sorted(client_meetings, key=lambda item: item.meeting_datetime) if m.status == "planned" and m.meeting_datetime >= datetime.utcnow()), None)
        try:
            risk = self._client_risk(client.id)
        except Exception:
            risk = {"risk_level": "unknown", "risk_score_local": "", "risk_reasons": [], "recommended_actions": []}

        y = rect.y + 58
        y = self.draw_client_detail_section(surface, rect, y, "Основная информация", [
            ("ИНН", client.inn or "Не указан"),
            ("Контактное лицо", client.contact_person or "Не указано"),
            ("Статус клиента", _ru(client.relationship_status)),
            ("Отрасль", client.industry),
            ("Сегмент", client.segment),
            ("Оценка клиента", client.health_score),
            ("Проникновение продуктов", client.product_penetration or "Не указано"),
        ], max_rows=4)

        date_rows = []
        if client.next_contact_due:
            date_rows.append(("Следующий контакт", _fmt(client.next_contact_due)))
        if next_meeting:
            date_rows.append(("Ближайшая встреча", _fmt(next_meeting.meeting_datetime)))
        for project in sorted(client_projects, key=lambda item: item.planned_end_date or date.max)[:1]:
            date_rows.append(("Срок по ключевому проекту", _fmt(project.planned_end_date)))
        for item in business_dates[:3]:
            date_rows.append((item.title, _fmt(item.date)))
        y = self.draw_client_detail_section(surface, rect, y, "Важные даты", date_rows[:3] or [("Даты", "Нет данных")], max_rows=3)

        description = client.company_description or client.business_profile or "Описание компании пока не заполнено."
        y = self.draw_client_text_section(surface, rect, y, "Описание компании", description, max_lines=2)

        indicator_rows = []
        for item in indicators[:5]:
            fact = self.format_indicator_value(item.fact_value, item.unit)
            plan = self.format_indicator_value(item.plan_value, item.unit)
            forecast = self.format_indicator_value(item.forecast_value, item.unit)
            completion = self.format_completion(item.fact_value, item.plan_value)
            indicator_rows.append((item.indicator_name, f"Факт {fact or '-'} / План {plan or '-'} / {completion or 'Прогноз ' + (forecast or '-')}"))
        y = self.draw_client_detail_section(surface, rect, y, "Ключевые показатели", indicator_rows or [("Показатели", "Нет данных")], max_rows=3)

        project_rows = [(p.title, f"{_ru(p.status)}, срок {_fmt(p.planned_end_date)}, прогресс {p.progress_percent}%") for p in client_projects[:3]]
        if len(client_projects) > 3:
            project_rows.append(("Дополнительно", f"и ещё {len(client_projects) - 3} проектов"))
        y = self.draw_client_detail_section(surface, rect, y, "Проекты", project_rows or [("Проекты", "Нет активных проектов")], max_rows=4)

        risk_items = [(task.title, f"{_ru(task.status)}, срок {_fmt(task.due_date)}") for task in client_tasks if task.status in {"open", "in_progress", "blocked", "overdue"}][:2]
        risk_items.extend(("Риск", reason) for reason in risk.get("risk_reasons", [])[:2])
        y = self.draw_client_detail_section(surface, rect, y, "Задачи и риски", risk_items or [("Риски", "Критичные пункты не найдены")], max_rows=3)

        team_rows = []
        for member in team[:4]:
            team_rows.append((member.full_name, f"{_ru(member.role)}; зона ответственности: проектная работа"))
        y = self.draw_client_detail_section(surface, rect, y, "Команда по клиенту", team_rows or [("Команда", "Нет данных")], max_rows=4)

        user = self.state.current_user
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 104, 174, 28), "Сформировать справку", lambda client=client: self.generate_onepage(client), disabled=user.role not in {"admin", "sponsor"})
        self.draw_button(surface, pygame.Rect(rect.x + 206, rect.bottom - 104, 174, 28), "Сформировать PDF", lambda client=client: self.generate_client_pdf(client), disabled=user.role not in {"admin", "sponsor"})
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 68, 112, 28), "Проекты", lambda client=client: self.open_client_projects(client))
        self.draw_button(surface, pygame.Rect(rect.x + 142, rect.bottom - 68, 102, 28), "Задачи", lambda client=client: self.open_client_tasks(client))
        self.draw_button(surface, pygame.Rect(rect.x + 258, rect.bottom - 68, 122, 28), "Встреча", lambda meeting=next_meeting: self.open_meeting_from_dashboard(meeting.id) if meeting else None, disabled=not next_meeting)

    def draw_client_detail_section(self, surface, rect, y, title, rows, max_rows=4):
        if y > rect.bottom - 134:
            return y
        draw_text(surface, self.fonts["small"], title, (rect.x + 16, y), COLORS["primary"])
        y += 18
        for label, value in rows[:max_rows]:
            draw_text(surface, self.fonts["small"], ellipsize(f"{label}: {value}", self.fonts["small"], rect.width - 32), (rect.x + 16, y))
            y += 18
        return y + 6

    def draw_client_text_section(self, surface, rect, y, title, text, max_lines=2):
        if y > rect.bottom - 134:
            return y
        draw_text(surface, self.fonts["small"], title, (rect.x + 16, y), COLORS["primary"])
        y += 18
        words = str(text or "").split()
        line = ""
        lines = []
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.fonts["small"].size(candidate)[0] <= rect.width - 32:
                line = candidate
            else:
                lines.append(line)
                line = word
            if len(lines) >= max_lines:
                break
        if line and len(lines) < max_lines:
            lines.append(line)
        for value in lines[:max_lines]:
            draw_text(surface, self.fonts["small"], value, (rect.x + 16, y), COLORS["muted"])
            y += 18
        return y + 6

    def draw_projects(self, surface, mouse):
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        q = self.draw_input(surface, "project_search", pygame.Rect(18, 110, 210, 34), "Поиск")
        client_filter = self.draw_select(surface, "project_client", pygame.Rect(240, 110, 180, 34), ["Все"] + [c.name for c in clients])
        stage_options = sorted({p.stage for p in projects if p.stage})
        status = self.draw_select(surface, "project_status", pygame.Rect(594, 110, 150, 34), _ru_options(sorted({p.status for p in projects if p.status}), STATUS_LABELS))
        stage = self.draw_select(surface, "project_stage", pygame.Rect(432, 110, 150, 34), _ru_options(stage_options, STAGE_LABELS))
        stage_code = _code_from_ru(stage, STAGE_LABELS)
        status_code = _code_from_ru(status, STATUS_LABELS)
        self.draw_button(surface, pygame.Rect(756, 110, 150, 34), "Создать проект", self.open_project_modal, disabled=self.state.current_user.role != "admin")
        rows = []
        for p in projects:
            client = client_by_id.get(p.client_id)
            row = {"id": p.id, "client": client.name if client else "", "title": p.title, "stage": _ru(p.stage), "progress": f"{p.progress_percent}%", "date": _fmt(p.planned_end_date), "revenue": p.expected_revenue, "status": _ru(p.status)}
            if _contains(row, q) and (client_filter == "Все" or row["client"] == client_filter) and (stage == "Все" or p.stage == stage_code) and (status == "Все" or p.status == status_code):
                rows.append(row)
        self.draw_table_block(surface, "Проекты", pygame.Rect(18, 175, 820, 580), [
            {"key": "client", "title": "Клиент", "width": 150}, {"key": "title", "title": "Проект", "width": 190},
            {"key": "stage", "title": "Этап", "width": 120}, {"key": "progress", "title": "Прогресс", "width": 85}, {"key": "date", "title": "Дата", "width": 105}, {"key": "revenue", "title": "Выручка", "width": 100}, {"key": "status", "title": "Статус", "width": 70},
        ], rows, "projects", lambda row: self.select("project", row["id"]), self.state.selected.get("project"))
        self.draw_project_detail(surface, pygame.Rect(858, 110, 404, 645), project_by_id.get(self.state.selected.get("project")), deals, tasks, meetings)

    def draw_project_detail(self, surface, rect, project, deals, tasks, meetings):
        draw_panel(surface, rect, "Детали проекта", self.fonts["small"], self.fonts["subtitle"])
        if not project:
            draw_text(surface, self.fonts["normal"], "Выберите проект", (rect.x + 16, rect.y + 66), COLORS["muted"])
            return
        y = rect.y + 60
        for label, value in [("Название", project.title), ("Этап", _ru(project.stage)), ("Прогресс", f"{project.progress_percent}%"), ("План", _fmt(project.planned_end_date)), ("Выручка", project.expected_revenue), ("Статус", _ru(project.status))]:
            draw_text(surface, self.fonts["small"], f"{label}: {value}", (rect.x + 16, y))
            y += 24
        y += 12
        draw_text(surface, self.fonts["small"], f"Связанные сделки: {len([d for d in deals if d.project_id == project.id])}", (rect.x + 16, y)); y += 24
        draw_text(surface, self.fonts["small"], f"Задачи: {len([t for t in tasks if t.project_id == project.id])}", (rect.x + 16, y)); y += 24
        draw_text(surface, self.fonts["small"], f"Встречи клиента: {len([m for m in meetings if m.client_id == project.client_id])}", (rect.x + 16, y))
        y += 32
        draw_text(surface, self.fonts["small"], "Дорожная карта:", (rect.x + 16, y), COLORS["muted"]); y += 22
        steps = repositories.get_roadmap_steps_by_project(project.id)
        for step in steps[:4]:
            color = COLORS["danger"] if step.status == "delayed" else COLORS["success"] if step.status == "done" else COLORS["text"]
            draw_text(surface, self.fonts["small"], ellipsize(f"{step.order_index}. {step.title} / {_ru(step.status)} / {_fmt(step.planned_end_date)}", self.fonts["small"], rect.width - 32), (rect.x + 16, y), color)
            y += 20
        if not steps:
            draw_text(surface, self.fonts["small"], "Этапов нет", (rect.x + 16, y), COLORS["muted"]); y += 20
        draw_text(surface, self.fonts["small"], "Команда проекта:", (rect.x + 16, y + 4), COLORS["muted"]); y += 26
        team = repositories.get_project_team(project.id)
        for member in team[:4]:
            draw_text(surface, self.fonts["small"], ellipsize(f"{_ru(member.role)}: {member.full_name} ({_ru(member.status)})", self.fonts["small"], rect.width - 32), (rect.x + 16, y))
            y += 20
        if project.status == "active":
            active_roles = {member.role for member in team if member.status == "active"}
            missing = sorted(repositories.REQUIRED_PROJECT_ROLES - active_roles)
            if missing:
                draw_text(surface, self.fonts["small"], "Не хватает: " + ", ".join(_ru(role) for role in missing), (rect.x + 16, y), COLORS["danger"])
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 150, 180, 30), "Добавить этап", lambda project=project: self.open_roadmap_step_modal(project), disabled=self.state.current_user.role not in {"admin", "sponsor"})
        self.draw_button(surface, pygame.Rect(rect.x + 208, rect.bottom - 150, 176, 30), "Статус этапа", lambda project=project: self.open_roadmap_status_modal(project), disabled=not steps)
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 112, 180, 30), "Добавить участника", lambda project=project: self.open_team_member_modal(project), disabled=self.state.current_user.role not in {"admin", "sponsor"})
        self.draw_button(surface, pygame.Rect(rect.x + 208, rect.bottom - 112, 176, 30), "Заменить", lambda project=project: self.open_team_replace_modal(project), disabled=not team)
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 72, 180, 34), "Редактировать проект", lambda: self.open_project_modal(project), disabled=self.state.current_user.role != "admin")

    def draw_tasks(self, surface, mouse):
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        q = self.draw_input(surface, "task_search", pygame.Rect(18, 110, 180, 34), "Поиск")
        client_filter = self.draw_select(surface, "task_client", pygame.Rect(210, 110, 155, 34), ["Все"] + [c.name for c in clients])
        status = self.draw_select(surface, "task_status", pygame.Rect(377, 110, 135, 34), _ru_options(["open", "in_progress", "blocked", "done", "overdue", "cancelled"], STATUS_LABELS))
        priority = self.draw_select(surface, "task_priority", pygame.Rect(524, 110, 120, 34), _ru_options(["low", "medium", "high"], PRIORITY_LABELS))
        status_code = _code_from_ru(status, STATUS_LABELS)
        priority_code = _code_from_ru(priority, PRIORITY_LABELS)
        assignee = self.draw_select(surface, "task_assignee", pygame.Rect(656, 110, 160, 34), ["Все"] + [u.full_name for u in users])
        self.draw_button(surface, pygame.Rect(828, 110, 140, 34), "Создать задачу", self.open_task_modal, disabled=self.state.current_user.role not in {"admin", "sponsor"})
        rows = []
        for t in tasks:
            client = client_by_id.get(t.client_id)
            project = project_by_id.get(t.project_id)
            owner = user_by_id.get(t.assignee_user_id)
            bg = {"overdue": COLORS["danger_soft"], "blocked": COLORS["warning_soft"], "done": COLORS["success_soft"]}.get(t.status)
            row = {"id": t.id, "client": client.name if client else "", "project": project.title if project else "", "title": t.title, "assignee": owner.full_name if owner else "", "due": _fmt(t.due_date), "status": _ru(t.status), "priority": _ru(t.priority), "_bg": bg}
            if _contains(row, q) and (client_filter == "Все" or row["client"] == client_filter) and (status == "Все" or t.status == status_code) and (priority == "Все" or t.priority == priority_code) and (assignee == "Все" or row["assignee"] == assignee):
                rows.append(row)
        self.draw_table_block(surface, "Задачи", pygame.Rect(18, 175, 820, 580), [
            {"key": "client", "title": "Клиент", "width": 125}, {"key": "project", "title": "Проект", "width": 120},
            {"key": "title", "title": "Задача", "width": 210}, {"key": "assignee", "title": "Исполнитель", "width": 130}, {"key": "due", "title": "Срок", "width": 95}, {"key": "status", "title": "Статус", "width": 90}, {"key": "priority", "title": "Приор.", "width": 50},
        ], rows, "tasks", lambda row: self.select("task", row["id"]), self.state.selected.get("task"))
        task_by_id = {t.id: t for t in tasks}
        self.draw_task_detail(surface, pygame.Rect(858, 110, 404, 645), task_by_id.get(self.state.selected.get("task")), client_by_id, project_by_id, user_by_id)

    def draw_task_detail(self, surface, rect, task, client_by_id, project_by_id, user_by_id):
        draw_panel(surface, rect, "Детали задачи", self.fonts["small"], self.fonts["subtitle"])
        if not task:
            draw_text(surface, self.fonts["normal"], "Выберите задачу", (rect.x + 16, rect.y + 66), COLORS["muted"])
            return
        client = client_by_id.get(task.client_id)
        project = project_by_id.get(task.project_id)
        owner = user_by_id.get(task.assignee_user_id)
        y = rect.y + 58
        for label, value in [("Задача", task.title), ("Описание", task.description or ""), ("Клиент", client.name if client else ""), ("Проект", project.title if project else ""), ("Исполнитель", owner.full_name if owner else ""), ("Срок", _fmt(task.due_date)), ("Статус", _ru(task.status)), ("Приоритет", _ru(task.priority))]:
            draw_text(surface, self.fonts["small"], ellipsize(f"{label}: {value}", self.fonts["small"], rect.width - 32), (rect.x + 16, y))
            y += 23
        draw_text(surface, self.fonts["small"], "Комментарии:", (rect.x + 16, y + 8), COLORS["muted"])
        y += 34
        for comment in self.task_comments(task.id)[:5]:
            author = user_by_id.get(comment.author_user_id)
            draw_text(surface, self.fonts["small"], ellipsize(f"{author.full_name if author else ''}: {comment.text}", self.fonts["small"], rect.width - 32), (rect.x + 16, y))
            y += 22
        button_y = rect.bottom - 192
        self.draw_button(surface, pygame.Rect(rect.x + 16, button_y, 176, 32), "Изменить статус", lambda: self.open_task_status_modal(task))
        self.draw_button(surface, pygame.Rect(rect.x + 208, button_y, 176, 32), "Изменить срок", lambda: self.open_task_due_modal(task))
        self.draw_button(surface, pygame.Rect(rect.x + 16, button_y + 42, 176, 32), "Сменить исполнителя", lambda: self.open_task_assignee_modal(task))
        self.draw_button(surface, pygame.Rect(rect.x + 208, button_y + 42, 176, 32), "Добавить комментарий", lambda: self.open_task_comment_modal(task))
        self.draw_button(surface, pygame.Rect(rect.x + 16, button_y + 84, 176, 32), "Закрыть", lambda: self.run_action(lambda: repositories.close_task(self.state.current_user, task.id), "Задача закрыта"))
        self.draw_button(surface, pygame.Rect(rect.x + 208, button_y + 84, 176, 32), "Отменить", lambda: self.run_action(lambda: repositories.cancel_task(self.state.current_user, task.id), "Задача отменена"))

    def task_comments(self, task_id):
        with get_session() as session:
            return list(session.execute(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at.desc())).scalars())

    def draw_deals(self, surface, mouse):
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        q = self.draw_input(surface, "deal_search", pygame.Rect(18, 110, 180, 34), "Поиск")
        client_filter = self.draw_select(surface, "deal_client", pygame.Rect(210, 110, 155, 34), ["Все"] + [c.name for c in clients])
        stage = self.draw_select(surface, "deal_stage", pygame.Rect(377, 110, 130, 34), _ru_options(sorted({d.stage for d in deals if d.stage}), STAGE_LABELS))
        stage_code = _code_from_ru(stage, STAGE_LABELS)
        status = self.draw_select(surface, "deal_status", pygame.Rect(519, 110, 130, 34), _ru_options(sorted({d.status for d in deals if d.status}), STATUS_LABELS))
        status_code = _code_from_ru(status, STATUS_LABELS)
        offer = self.draw_select(surface, "deal_offer", pygame.Rect(661, 110, 115, 34), ["Все", "есть", "нет"])
        self.draw_button(surface, pygame.Rect(788, 110, 140, 34), "Создать сделку", self.open_deal_modal, disabled=self.state.current_user.role != "admin")
        rows = []
        for d in deals:
            client = client_by_id.get(d.client_id)
            project = project_by_id.get(d.project_id)
            row = {"id": d.id, "client": client.name if client else "", "project": project.title if project else "", "name": d.name, "stage": _ru(d.stage), "amount": d.amount, "prob": d.probability, "offer": "есть" if d.commercial_offer_exists else "нет", "last": _fmt(d.last_activity_date), "status": _ru(d.status)}
            if _contains(row, q) and (client_filter == "Все" or row["client"] == client_filter) and (stage == "Все" or d.stage == stage_code) and (status == "Все" or d.status == status_code) and (offer == "Все" or row["offer"] == offer):
                rows.append(row)
        self.draw_table_block(surface, "Сделки", pygame.Rect(18, 175, 820, 580), [
            {"key": "client", "title": "Клиент", "width": 120}, {"key": "project", "title": "Проект", "width": 105}, {"key": "name", "title": "Сделка", "width": 150}, {"key": "stage", "title": "Этап", "width": 100}, {"key": "amount", "title": "Сумма", "width": 90}, {"key": "prob", "title": "%", "width": 50}, {"key": "offer", "title": "КП", "width": 55}, {"key": "last", "title": "Активность", "width": 100}, {"key": "status", "title": "Статус", "width": 50},
        ], rows, "deals", lambda row: self.select("deal", row["id"]), self.state.selected.get("deal"))
        deal_by_id = {d.id: d for d in deals}
        self.draw_deal_detail(surface, pygame.Rect(858, 110, 404, 645), deal_by_id.get(self.state.selected.get("deal")))

    def draw_deal_detail(self, surface, rect, deal):
        draw_panel(surface, rect, "Детали сделки", self.fonts["small"], self.fonts["subtitle"])
        if not deal:
            draw_text(surface, self.fonts["normal"], "Выберите сделку", (rect.x + 16, rect.y + 66), COLORS["muted"])
            return
        y = rect.y + 60
        for label, value in [("Сделка", deal.name), ("Этап", _ru(deal.stage)), ("Сумма", deal.amount), ("Вероятность", deal.probability), ("КП", "есть" if deal.commercial_offer_exists else "нет"), ("Последняя активность", _fmt(deal.last_activity_date)), ("Статус", _ru(deal.status))]:
            draw_text(surface, self.fonts["small"], f"{label}: {value}", (rect.x + 16, y)); y += 24
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 150, 176, 32), "Изменить этап", lambda: self.open_deal_field_modal(deal, "stage"))
        self.draw_button(surface, pygame.Rect(rect.x + 208, rect.bottom - 150, 176, 32), "Вероятность", lambda: self.open_deal_field_modal(deal, "probability"))
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 108, 176, 32), "Переключить КП", lambda: self.run_action(lambda: repositories.update_deal_commercial_offer(self.state.current_user, deal.id, not deal.commercial_offer_exists), "КП обновлено"))
        self.draw_button(surface, pygame.Rect(rect.x + 208, rect.bottom - 108, 176, 32), "Статус", lambda: self.open_deal_field_modal(deal, "status"))

    def draw_calendar(self, surface, mouse):
        if not self.state.week_start:
            today = date.today()
            self.state.week_start = today - timedelta(days=today.weekday())
        self.draw_button(surface, pygame.Rect(18, 108, 100, 34), "Сегодня", self.calendar_today)
        self.draw_button(surface, pygame.Rect(130, 108, 110, 34), "< Неделя", lambda: self.shift_week(-1))
        self.draw_button(surface, pygame.Rect(252, 108, 110, 34), "Неделя >", lambda: self.shift_week(1))
        self.draw_button(surface, pygame.Rect(374, 108, 140, 34), "Создать встречу", self.open_meeting_modal, disabled=self.state.current_user.role not in {"admin", "sponsor"})
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        week_start = self.state.week_start
        col_w = 118
        cal_rect = pygame.Rect(18, 170, 850, 520)
        for idx in range(7):
            day = week_start + timedelta(days=idx)
            rect = pygame.Rect(cal_rect.x + idx * col_w, cal_rect.y, col_w - 6, cal_rect.height)
            draw_panel(surface, rect)
            draw_text(surface, self.fonts["small"], day.strftime("%a %d.%m"), (rect.x + 8, rect.y + 8), COLORS["muted"])
            y = rect.y + 36
            day_meetings = [m for m in meetings if m.meeting_datetime.date() == day]
            visible_meetings = sorted(day_meetings, key=lambda m: m.meeting_datetime)[:3]
            for meeting in visible_meetings:
                card = pygame.Rect(rect.x + 6, y, rect.width - 12, 58)
                color = COLORS["selected"] if self.state.selected.get("meeting") == meeting.id else COLORS["table_zebra"]
                pygame.draw.rect(surface, color, card, border_radius=6)
                pygame.draw.rect(surface, COLORS["border"], card, width=1, border_radius=6)
                client = client_by_id.get(meeting.client_id)
                draw_text(surface, self.fonts["small"], meeting.meeting_datetime.strftime("%H:%M"), (card.x + 6, card.y + 5), COLORS["primary"])
                draw_text(surface, self.fonts["small"], ellipsize(client.name if client else "", self.fonts["small"], card.width - 12), (card.x + 6, card.y + 24))
                draw_text(surface, self.fonts["small"], ellipsize(meeting.title, self.fonts["small"], card.width - 12), (card.x + 6, card.y + 40), COLORS["muted"])
                self.add_widget(Button(card, "", lambda meeting=meeting: self.select("meeting", meeting.id)))
                y += 66
            hidden_count = max(0, len(day_meetings) - len(visible_meetings))
            if hidden_count:
                draw_text(surface, self.fonts["small"], f"+ ещё {hidden_count}", (rect.x + 8, min(rect.bottom - 24, y)), COLORS["muted"])
        overlaps = self.find_overlaps(meetings)
        draw_panel(surface, pygame.Rect(18, 705, 850, 50))
        draw_text(surface, self.fonts["small"], "Накладки: " + (", ".join(overlaps[:3]) if overlaps else "нет"), (32, 722), COLORS["danger"] if overlaps else COLORS["muted"])
        meeting_by_id = {m.id: m for m in meetings}
        self.draw_meeting_detail(surface, pygame.Rect(890, 110, 372, 645), meeting_by_id.get(self.state.selected.get("meeting")), client_by_id)

    def draw_meeting_detail(self, surface, rect, meeting, client_by_id):
        draw_panel(surface, rect, "Встреча", self.fonts["small"], self.fonts["subtitle"])
        if not meeting:
            draw_text(surface, self.fonts["normal"], "Выберите встречу", (rect.x + 16, rect.y + 66), COLORS["muted"])
            return
        client = client_by_id.get(meeting.client_id)
        y = rect.y + 60
        for label, value in [("Дата/время", _fmt(meeting.meeting_datetime)), ("Длительность", meeting.duration_minutes), ("Клиент", client.name if client else ""), ("Участники", meeting.participants or ""), ("Повестка", meeting.agenda or ""), ("Итоги", meeting.summary or ""), ("Следующие шаги", meeting.next_steps or ""), ("Статус", _ru(meeting.status))]:
            draw_text(surface, self.fonts["small"], ellipsize(f"{label}: {value}", self.fonts["small"], rect.width - 32), (rect.x + 16, y)); y += 24
        latest_brief = meeting_brief_service.get_latest_meeting_brief(meeting.id)
        if latest_brief:
            draw_text(surface, self.fonts["small"], "Материалы: " + _fmt(latest_brief.generated_at), (rect.x + 16, y + 4), COLORS["success"])
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 190, 160, 30), "Подготовить", lambda meeting=meeting: self.generate_meeting_brief(meeting))
        self.draw_button(surface, pygame.Rect(rect.x + 190, rect.bottom - 190, 160, 30), "Открыть материалы", lambda meeting=meeting: self.open_latest_meeting_brief(meeting), disabled=not latest_brief)
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 150, 160, 32), "Изменить статус", lambda: self.open_meeting_status_modal(meeting))
        self.draw_button(surface, pygame.Rect(rect.x + 190, rect.bottom - 150, 160, 32), "Добавить итоги", lambda: self.open_meeting_summary_modal(meeting))
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.bottom - 108, 160, 32), "Перенести", lambda: self.open_meeting_move_modal(meeting))

    def find_overlaps(self, meetings):
        result = []
        by_day = defaultdict(list)
        for m in meetings:
            if m.status == "planned":
                by_day[m.meeting_datetime.date()].append(m)
        for day, items in by_day.items():
            items = sorted(items, key=lambda m: m.meeting_datetime)
            for first, second in zip(items, items[1:]):
                first_end = first.meeting_datetime + timedelta(minutes=first.duration_minutes)
                if first_end > second.meeting_datetime:
                    result.append(f"{day}: {first.title} / {second.title}")
        return result

    def draw_metrics(self, surface, mouse):
        clients = repositories.get_clients_for_user(self.state.current_user)
        client_options = [c.name for c in clients]
        if client_options and self.state.filters.get("metric_client") not in client_options:
            self.state.filters["metric_client"] = client_options[0]
        client_name = self.draw_select(surface, "metric_client", pygame.Rect(18, 110, 240, 34), client_options or ["Нет клиентов"])
        points = self.draw_select(surface, "metric_points", pygame.Rect(274, 110, 150, 34), ["4", "8", "12"])
        self.draw_button(surface, pygame.Rect(440, 110, 160, 34), "Добавить метрику", self.open_metric_modal, disabled=not clients)
        client = next((c for c in clients if c.name == client_name), clients[0] if clients else None)
        metrics = repositories.get_metrics_by_client(client.id) if client else []
        metrics = metrics[-min(5, int(points or "5")) :]
        latest = metrics[-1] if metrics else None
        kpis = [
            ("План", _fmt_money(latest.revenue_plan) if latest else "-"),
            ("Факт", _fmt_money(latest.revenue_fact) if latest else "-"),
            ("Выполнение %", f"{round(latest.revenue_fact / latest.revenue_plan * 100)}%" if latest and latest.revenue_plan else "-"),
            ("Активность", _fmt_number(latest.activity_score) if latest else "-"),
            ("NPS", _fmt_number(latest.nps) if latest else "-"),
            ("Риск", _fmt_number(latest.risk_score) if latest else "-"),
        ]
        x = 18
        for label, value in kpis:
            self.draw_kpi(surface, pygame.Rect(x, 170, 194, 78), label, str(value))
            x += 210
        self.draw_chart(surface, pygame.Rect(18, 280, 610, 175), metrics, [("revenue_plan", COLORS["primary"]), ("revenue_fact", COLORS["success"])], "План / Факт")
        self.draw_chart(surface, pygame.Rect(654, 280, 290, 175), metrics, [("activity_score", COLORS["primary"])], "Активность")
        self.draw_chart(surface, pygame.Rect(972, 280, 290, 175), metrics, [("risk_score", COLORS["danger"])], "Риск")
        rows = []
        for m in metrics:
            pct = f"{round(m.revenue_fact / m.revenue_plan * 100)}%" if m.revenue_plan else ""
            rows.append({"id": m.id, "date": _fmt(m.metric_date), "plan": _fmt_money(m.revenue_plan), "fact": _fmt_money(m.revenue_fact), "pct": pct, "activity": _fmt_number(m.activity_score), "nps": _fmt_number(m.nps), "risk": _fmt_number(m.risk_score), "comment": m.comment or ""})
        self.draw_table_block(surface, "Метрики", pygame.Rect(18, 515, 1244, 240), [
            {"key": "date", "title": "Дата", "width": 120}, {"key": "plan", "title": "План", "width": 130}, {"key": "fact", "title": "Факт", "width": 130}, {"key": "pct", "title": "Выполнение", "width": 120}, {"key": "activity", "title": "Активность", "width": 110}, {"key": "nps", "title": "NPS", "width": 90}, {"key": "risk", "title": "Риск", "width": 90}, {"key": "comment", "title": "Комментарий", "width": 450},
        ], rows, "metrics")

    def draw_chart(self, surface, rect, metrics, series, title):
        draw_panel(surface, rect)
        draw_text(surface, self.fonts["small"], title, (rect.x + 12, rect.y + 10), COLORS["muted"])
        plot = pygame.Rect(rect.x + 40, rect.y + 38, rect.width - 58, rect.height - 58)
        pygame.draw.line(surface, COLORS["border"], plot.bottomleft, plot.topleft, 1)
        pygame.draw.line(surface, COLORS["border"], plot.bottomleft, plot.bottomright, 1)
        if len(metrics) < 2:
            draw_text(surface, self.fonts["small"], "Недостаточно данных", (plot.x + 16, plot.y + 40), COLORS["muted"])
            return
        values = []
        for field, color in series:
            values.extend([float(getattr(m, field) or 0) for m in metrics])
        low, high = min(values), max(values)
        if high == low:
            high += 1
        for field, color in series:
            points = []
            for idx, m in enumerate(metrics):
                x = plot.x + idx * plot.width / max(1, len(metrics) - 1)
                y = plot.bottom - (float(getattr(m, field) or 0) - low) / (high - low) * plot.height
                points.append((int(x), int(y)))
            if len(points) > 1:
                pygame.draw.lines(surface, color, False, points, 2)
            for point in points:
                pygame.draw.circle(surface, color, point, 3)

    def draw_messages(self, surface, mouse):
        clients, projects, tasks, deals, meetings, notifications, users, client_by_id, project_by_id, user_by_id = self.data()
        messages = repositories.get_messages_for_user(self.state.current_user)
        search = self.draw_input(surface, "message_search", pygame.Rect(18, 110, 190, 34), "Поиск")
        client_filter = self.draw_select(surface, "message_client", pygame.Rect(220, 110, 128, 34), ["Все"] + [c.name for c in clients])
        dialogs = {}
        for msg in messages:
            key = msg.client_id or msg.receiver_user_id or msg.sender_user_id or msg.id
            title = client_by_id.get(msg.client_id).name if msg.client_id in client_by_id else (user_by_id.get(msg.receiver_user_id).full_name if msg.receiver_user_id in user_by_id else "Без контекста")
            if key not in dialogs or msg.created_at > dialogs[key]["created_at"]:
                dialogs[key] = {"id": key, "title": title, "subtitle": f"{msg.message_type}: {msg.title}", "created_at": msg.created_at, "client": title if msg.client_id else ""}
        dialog_rows = [row for row in dialogs.values() if _contains(row, search) and (client_filter == "Все" or row["client"] == client_filter)]
        dialog_list = ScrollableList(pygame.Rect(18, 160, 330, 595), dialog_rows, self.state.scrolls.get("dialogs", 0), self.state.selected.get("dialog"), lambda row: self.select_dialog(row["id"], messages))
        dialog_list.name = "dialogs"
        dialog_list.draw(surface, self.fonts["small"], self.fonts["small"], mouse)
        self.state.scrolls["dialogs"] = dialog_list.scroll_offset
        self.add_table(dialog_list)
        self.draw_chat(surface, pygame.Rect(370, 110, 892, 645), messages, user_by_id)

    def draw_chat(self, surface, rect, messages, user_by_id):
        draw_panel(surface, rect, "Диалог", self.fonts["small"], self.fonts["subtitle"])
        dialog = self.state.selected.get("dialog")
        history = [m for m in messages if (m.client_id or m.receiver_user_id or m.sender_user_id or m.id) == dialog] if dialog else []
        y = rect.y + 60
        for msg in sorted(history, key=lambda item: item.created_at)[-8:]:
            outgoing = msg.sender_user_id == self.state.current_user.id
            bubble_w = 460
            x = rect.right - bubble_w - 18 if outgoing else rect.x + 18
            bubble = pygame.Rect(x, y, bubble_w, 58)
            pygame.draw.rect(surface, COLORS["chat_out"] if outgoing else COLORS["chat_in"], bubble, border_radius=10)
            draw_text(surface, self.fonts["small"], ellipsize(msg.title, self.fonts["small"], bubble.width - 18), (bubble.x + 10, bubble.y + 8))
            draw_text(surface, self.fonts["small"], ellipsize(msg.body, self.fonts["small"], bubble.width - 18), (bubble.x + 10, bubble.y + 28), COLORS["muted"])
            draw_text(surface, self.fonts["small"], f"{_fmt(msg.created_at)} {_ru(msg.status)}", (bubble.x + 10, bubble.y + 44), COLORS["muted"])
            if msg.receiver_user_id == self.state.current_user.id and msg.status == "unread":
                self.draw_button(surface, pygame.Rect(bubble.right - 104, bubble.y + 6, 94, 24), "Прочитано", lambda msg=msg: self.run_action(lambda: repositories.mark_message_read(self.state.current_user, msg.id), "Сообщение прочитано"))
            y += 72
        input_rect = pygame.Rect(rect.x + 18, rect.bottom - 76, rect.width - 134, 60)
        self.draw_multiline_input(surface, "message_body", input_rect, "Введите сообщение")
        self.draw_button(surface, pygame.Rect(rect.right - 102, rect.bottom - 50, 84, 34), "Отправить", lambda: self.send_message(history))

    def select_dialog(self, dialog_id, messages):
        self.state.selected["dialog"] = dialog_id
        for msg in messages:
            key = msg.client_id or msg.receiver_user_id or msg.sender_user_id or msg.id
            if key == dialog_id and msg.receiver_user_id == self.state.current_user.id and msg.status == "unread":
                try:
                    repositories.mark_message_read(self.state.current_user, msg.id)
                except Exception:
                    pass

    def draw_notification_panel(self, surface, mouse):
        rect = pygame.Rect(WIDTH - 390, 78, 372, HEIGHT - 96)
        draw_panel(surface, rect, "Уведомления", self.fonts["small"], self.fonts["subtitle"])
        notifications = repositories.get_notifications_for_user(self.state.current_user, limit=5)
        rows = []
        ordered = sorted(notifications, key=lambda item: (item.status == "read", item.created_at), reverse=False)[:5]
        for n in ordered:
            target = "задача" if n.task_id else "встреча" if n.meeting_id else "клиент" if n.client_id else ""
            rows.append({"id": n.id, "title": n.title, "subtitle": f"{ellipsize(n.body, self.fonts['small'], 220)} · {_fmt(n.created_at)} · {target}".strip(" ·")})
        draw_text(surface, self.fonts["small"], f"Непрочитанные: {self._notification_summary()['unread_count']}", (rect.x + 16, rect.y + 58), COLORS["muted"])
        notif_list = ScrollableList(pygame.Rect(rect.x + 16, rect.y + 88, rect.width - 32, 330), rows, self.state.scrolls.get("notif_panel", 0), self.state.selected.get("notification"), lambda row: self.select("notification", row["id"]))
        notif_list.name = "notif_panel"
        notif_list.z_index = 160
        notif_list.draw(surface, self.fonts["small"], self.fonts["small"], mouse)
        self.state.scrolls["notif_panel"] = notif_list.scroll_offset
        self.add_table(notif_list)
        selected = next((n for n in notifications if n.id == self.state.selected.get("notification")), None)
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.y + 438, 150, 32), "Прочитано", lambda: self.read_notification(selected), disabled=not selected or selected.status == "read", z_index=170)
        self.draw_button(surface, pygame.Rect(rect.x + 182, rect.y + 438, 150, 32), "Открыть", lambda: self.open_notification_target(selected), disabled=not selected, z_index=170)
        self.draw_button(surface, pygame.Rect(rect.x + 16, rect.y + 486, 316, 32), "Все уведомления", lambda: self.switch_tab("Уведомления"), z_index=170)

    def draw_notifications_screen(self, surface, mouse):
        notifications = repositories.get_notifications_for_user(self.state.current_user, limit=200)
        type_filter = self.draw_select(surface, "notifications_type", pygame.Rect(18, 110, 180, 34), _ru_options(sorted({n.notification_type for n in notifications}), NOTIFICATION_TYPE_LABELS))
        status_filter = self.draw_select(surface, "notifications_status", pygame.Rect(210, 110, 150, 34), _ru_options(["unread", "read"], STATUS_LABELS))
        type_code = _code_from_ru(type_filter, NOTIFICATION_TYPE_LABELS)
        status_code = _code_from_ru(status_filter, STATUS_LABELS)
        selected = next((n for n in notifications if n.id == self.state.selected.get("notification_screen")), None)
        self.draw_button(surface, pygame.Rect(372, 110, 190, 34), "Отметить прочитанным", lambda: self.read_notification(selected), disabled=not selected or selected.status == "read")
        rows = []
        for n in notifications:
            if type_filter != "Все" and n.notification_type != type_code:
                continue
            if status_filter != "Все" and n.status != status_code:
                continue
            rows.append({"id": n.id, "type": _ru(n.notification_type), "title": n.title, "body": ellipsize(n.body, self.fonts["small"], 500), "status": _ru(n.status), "created": _fmt(n.created_at)})
        rows = sorted(rows, key=lambda row: (row["status"] == _ru("read"), row["created"]), reverse=False)
        self.draw_table_block(surface, "Уведомления", pygame.Rect(18, 175, 1244, 580), [
            {"key": "type", "title": "Тип", "width": 150},
            {"key": "title", "title": "Заголовок", "width": 230},
            {"key": "body", "title": "Текст", "width": 520},
            {"key": "status", "title": "Статус", "width": 110},
            {"key": "created", "title": "Создано", "width": 230},
        ], rows, "notifications", lambda row: self.select("notification_screen", row["id"]), self.state.selected.get("notification_screen"))

    def draw_onepage_screen(self, surface, mouse):
        clients = repositories.get_clients_for_user(self.state.current_user)
        client_options = [client.name for client in clients]
        if client_options and self.state.filters.get("onepage_client") not in client_options:
            self.state.filters["onepage_client"] = client_options[0]
        client_name = self.draw_select(surface, "onepage_client", pygame.Rect(18, 110, 260, 34), client_options or ["Нет клиентов"])
        client = next((item for item in clients if item.name == client_name), clients[0] if clients else None)
        self.draw_button(surface, pygame.Rect(294, 110, 170, 34), "Сформировать", lambda client=client: self.generate_onepage(client), disabled=not client)
        snapshot = onepage_service.get_latest_onepage(client.id) if client else None
        draw_panel(surface, pygame.Rect(18, 170, 1244, 585), "Справка по клиенту", self.fonts["small"], self.fonts["subtitle"])
        if not client:
            draw_text(surface, self.fonts["normal"], "Нет доступных клиентов", (42, 235), COLORS["muted"])
            return
        if not snapshot:
            draw_text(surface, self.fonts["normal"], "Справка ещё не сформирована. Нажмите “Сформировать”.", (42, 235), COLORS["muted"])
            return
        y = 230
        for line in snapshot.summary_text.splitlines()[:18]:
            draw_text(surface, self.fonts["small"], ellipsize(line, self.fonts["small"], 1160), (42, y))
            y += 24
        draw_text(surface, self.fonts["small"], f"Сформировано: {_fmt(snapshot.generated_at)}", (42, 712), COLORS["muted"])

    def draw_daily_digest_screen(self, surface, mouse):
        self.draw_button(surface, pygame.Rect(18, 110, 190, 34), "Сформировать сводку", self.generate_daily_digest)
        digest = daily_digest_service.get_latest_daily_digest()
        draw_panel(surface, pygame.Rect(18, 170, 1244, 585), "Ежедневная сводка", self.fonts["small"], self.fonts["subtitle"])
        if not digest:
            draw_text(surface, self.fonts["normal"], "Ежедневная сводка ещё не сформирована.", (42, 235), COLORS["muted"])
            return
        y = 230
        for line in digest.digest_text.splitlines()[:18]:
            draw_text(surface, self.fonts["small"], ellipsize(line, self.fonts["small"], 1160), (42, y))
            y += 24
        draw_text(surface, self.fonts["small"], f"Дата: {_fmt(digest.digest_date)} · статус: {_ru(digest.status)}", (42, 712), COLORS["muted"])

    def draw_templates(self, surface, mouse):
        templates = list_templates()
        if templates and not self.state.selected_template:
            self.state.selected_template = templates[0]
        rows = [{"id": name, "title": TEMPLATE_NAMES.get(name, name), "subtitle": name} for name in templates]
        template_list = ScrollableList(pygame.Rect(18, 110, 330, 645), rows, self.state.scrolls.get("templates", 0), self.state.selected_template, lambda row: self.select_template(row["id"]))
        template_list.name = "templates"
        template_list.draw(surface, self.fonts["small"], self.fonts["small"], mouse)
        self.state.scrolls["templates"] = template_list.scroll_offset
        self.add_table(template_list)
        rect = pygame.Rect(370, 110, 892, 645)
        draw_panel(surface, rect, TEMPLATE_NAMES.get(self.state.selected_template, "Шаблон"), self.fonts["small"], self.fonts["subtitle"])
        if not self.state.selected_template:
            return
        draft = self.state.template_drafts.setdefault(self.state.selected_template, load_template(self.state.selected_template))
        state_key = ("template", self.state.selected_template)
        editor = MultiLineTextInput(pygame.Rect(rect.x + 18, rect.y + 60, rect.width - 36, 240), draft, "Текст шаблона", self.is_focused(state_key))
        editor.state_key = ("template", self.state.selected_template)
        editor.name = "template_editor"
        editor.draw(surface, self.fonts["small"], mouse)
        self.add_widget(editor)
        self.draw_button(surface, pygame.Rect(rect.x + 18, rect.y + 318, 120, 34), "Сохранить", self.save_template)
        self.draw_button(surface, pygame.Rect(rect.x + 150, rect.y + 318, 160, 34), "Сбросить", self.reset_template)
        self.draw_button(surface, pygame.Rect(rect.x + 322, rect.y + 318, 140, 34), "Предпросмотр", self.preview_template)
        draw_text(surface, self.fonts["small"], "Предпросмотр:", (rect.x + 18, rect.y + 380), COLORS["muted"])
        y = rect.y + 410
        for line in self.state.template_preview.splitlines()[:9]:
            draw_text(surface, self.fonts["small"], ellipsize(line, self.fonts["small"], rect.width - 36), (rect.x + 18, y))
            y += 22

    def draw_input(self, surface, key, rect, placeholder):
        state_key = ("filters", key)
        widget = self.add_widget(TextInput(rect, self.state.filters.get(key, ""), placeholder, self.is_focused(state_key)), name=key)
        widget.state_key = state_key
        widget.draw(surface, self.fonts["small"], self.state.mouse_pos)
        return widget.value

    def draw_multiline_input(self, surface, key, rect, placeholder):
        state_key = ("filters", key)
        widget = self.add_widget(MultiLineTextInput(rect, self.state.filters.get(key, ""), placeholder, self.is_focused(state_key)), name=key)
        widget.state_key = state_key
        widget.draw(surface, self.fonts["small"], self.state.mouse_pos)
        return widget.value

    def draw_select(self, surface, key, rect, options):
        current = self.state.filters.get(key, options[0] if options else "")
        if current not in options and options:
            current = options[0]
        state_key = ("filters", key)
        widget = self.add_widget(SelectBox(rect, options, current, self.is_select_open(state_key), lambda value, key=key: self.state.filters.__setitem__(key, value)), name=key)
        widget.state_key = state_key
        widget.draw(surface, self.fonts["small"], self.state.mouse_pos)
        return widget.value

    def draw_button(self, surface, rect, label, action, active=False, disabled=False, z_index=None, style="primary"):
        button = self.add_widget(Button(rect, label, action, active=active, disabled=disabled, style=style), z_index=z_index)
        button.draw(surface, self.fonts["small"], self.state.mouse_pos)
        return button

    def select(self, key, value):
        self.state.selected[key] = value
        self.base_surface_cache = None

    def run_action(self, action, success):
        try:
            action()
            self._invalidate_runtime_cache()
            self.toast(success)
        except Exception as exc:
            self.toast(str(exc), "error")

    def save_action(self, action, success):
        action()
        self._invalidate_runtime_cache()
        self.toast(success)

    def open_modal(self, title, fields, on_save):
        self.state.modal = {"title": title, "fields": fields, "values": {field["name"]: field.get("value", "") for field in fields}, "on_save": on_save}
        self.state.modal_error = ""
        self.state.focused_input_key = None
        self.state.open_select_key = None
        self.base_surface_cache = None

    def close_modal(self):
        self.state.modal = None
        self.state.modal_error = ""
        self.state.focused_input_key = None
        self.state.open_select_key = None
        self.base_surface_cache = None

    def draw_modal(self, surface, mouse):
        modal = self.state.modal
        rect = pygame.Rect(260, 60, 660, 700)
        fields = []
        widgets = []
        y = rect.y + 68
        for field in modal["fields"]:
            draw_text(surface, self.fonts["small"], field["label"], (rect.x + 24, y - 18), COLORS["muted"])
            value = modal["values"].get(field["name"], field.get("value", ""))
            state_key = ("modal", field["name"])
            if field.get("type") == "select":
                widget = SelectBox(pygame.Rect(rect.x + 24, y, 300, 34), field["options"], value, self.is_select_open(state_key))
            elif field.get("type") == "checkbox":
                widget = Checkbox(pygame.Rect(rect.x + 24, y, 300, 34), bool(value), field["label"])
            elif field.get("type") == "multiline":
                height = field.get("height", 110)
                widget = MultiLineTextInput(pygame.Rect(rect.x + 24, y, 580, height), str(value or ""), field["label"], self.is_focused(state_key))
            else:
                widget = TextInput(pygame.Rect(rect.x + 24, y, 580, 34), str(value or ""), field["label"], self.is_focused(state_key))
            widget.state_key = state_key
            widget.name = field["name"]
            widget.z_index = 220
            widgets.append(widget)
            fields.append((field, widget))
            y += (field.get("height", 34) if field.get("type") == "multiline" else 34) + 24
        save = Button(pygame.Rect(rect.right - 238, rect.bottom - 54, 100, 34), "Сохранить", lambda: self.save_modal(fields))
        cancel = Button(pygame.Rect(rect.right - 126, rect.bottom - 54, 100, 34), "Отмена", self.close_modal)
        save.z_index = 230
        cancel.z_index = 230
        widgets.extend([save, cancel])
        self.modal_widgets = widgets
        self.modal_fields = fields
        Modal(modal["title"], modal["fields"], modal["on_save"], self.close_modal, self.state.modal_error).draw(surface, self.fonts, mouse, widgets)
        self.draw_open_dropdowns(surface, self.modal_widgets)

    def save_modal(self, fields):
        values = {}
        for field, widget in fields:
            if isinstance(widget, Checkbox):
                values[field["name"]] = widget.checked
            else:
                values[field["name"]] = widget.value
        try:
            self.state.modal["on_save"](values)
            self.close_modal()
        except Exception as exc:
            self.state.modal_error = str(exc)
            self.toast(str(exc), "error")

    def save_modal_from_state(self):
        if not self.state.modal:
            return
        try:
            self.state.modal["on_save"](dict(self.state.modal["values"]))
            self.close_modal()
        except Exception as exc:
            self.state.modal_error = str(exc)
            self.toast(str(exc), "error")

    def open_client_modal(self):
        users = repositories.get_users()
        self.open_modal("Создать клиента", [
            {"name": "name", "label": "Название"}, {"name": "industry", "label": "Отрасль"}, {"name": "segment", "label": "Сегмент"},
            {"name": "priority", "label": "Приоритет", "type": "select", "options": _ru_options(["low", "medium", "high"], PRIORITY_LABELS)[1:], "value": _ru("medium")},
            {"name": "sponsor", "label": "Спонсор", "type": "select", "options": [u.login for u in users], "value": users[0].login if users else ""},
            {"name": "status", "label": "Статус отношений", "type": "select", "options": _ru_options(["active", "closed"], STATUS_LABELS)[1:], "value": _ru("active")}, {"name": "health", "label": "Оценка клиента", "value": "80"},
            {"name": "last", "label": "Последний контакт YYYY-MM-DD"}, {"name": "next", "label": "Следующий контакт YYYY-MM-DD"},
        ], self.save_client)

    def save_client(self, values):
        sponsor = repositories.get_user_by_login(values["sponsor"])
        priority = _code_from_ru(values["priority"], PRIORITY_LABELS)
        status = _code_from_ru(values["status"], STATUS_LABELS)
        repositories.create_client(self.state.current_user, values["name"], values["industry"], values["segment"], priority, sponsor.id, status, int(values["health"]), _parse_date(values["last"]), _parse_date(values["next"]))
        self.toast("Клиент создан")

    def open_project_modal(self, project=None):
        clients = repositories.get_clients_for_user(self.state.current_user)
        client = next((c for c in clients if c.id == self.state.selected.get("client")), clients[0] if clients else None)
        self.open_modal("Редактировать проект" if project else "Создать проект", [
            {"name": "client", "label": "Клиент", "type": "select", "options": [c.name for c in clients], "value": next((c.name for c in clients if project and c.id == project.client_id), client.name if client else "")},
            {"name": "title", "label": "Проект", "value": project.title if project else ""}, {"name": "stage", "label": "Этап", "type": "select", "options": _ru_options(["discovery", "proposal", "contract", "implementation", "support"], STAGE_LABELS)[1:], "value": _ru(project.stage if project else "discovery")},
            {"name": "planned", "label": "Плановая дата YYYY-MM-DD", "value": _fmt(project.planned_end_date) if project else ""},
            {"name": "progress", "label": "Прогресс", "value": project.progress_percent if project else "0"}, {"name": "revenue", "label": "Выручка", "value": project.expected_revenue if project else "0"},
            {"name": "status", "label": "Статус", "type": "select", "options": _ru_options(["active", "closed"], STATUS_LABELS)[1:], "value": _ru(project.status if project else "active")},
        ], lambda values, project=project: self.save_project(values, project))

    def save_project(self, values, project=None):
        client = next(c for c in repositories.get_clients_for_user(self.state.current_user) if c.name == values["client"])
        stage = _code_from_ru(values["stage"], STAGE_LABELS)
        status = _code_from_ru(values["status"], STATUS_LABELS)
        if project:
            repositories.update_project(self.state.current_user, project.id, {"stage": stage, "planned_end_date": _parse_date(values["planned"]), "progress_percent": int(values["progress"]), "expected_revenue": float(values["revenue"]), "status": status, "title": values["title"]})
            self.toast("Проект обновлён")
        else:
            repositories.create_project(self.state.current_user, client.id, values["title"], stage, _parse_date(values["planned"]), int(values["progress"]), float(values["revenue"]), status)
            self.toast("Проект создан")

    def open_task_modal(self):
        clients = repositories.get_clients_for_user(self.state.current_user)
        projects = repositories.get_projects_for_user(self.state.current_user)
        users = repositories.get_users()
        self.open_modal("Создать задачу", [
            {"name": "client", "label": "Клиент", "type": "select", "options": [c.name for c in clients], "value": clients[0].name if clients else ""},
            {"name": "project", "label": "Проект", "type": "select", "options": [""] + [p.title for p in projects], "value": ""},
            {"name": "title", "label": "Задача"}, {"name": "description", "label": "Описание", "type": "multiline", "height": 88},
            {"name": "assignee", "label": "Исполнитель", "type": "select", "options": [u.login for u in users], "value": users[0].login if users else ""},
            {"name": "due", "label": "Срок YYYY-MM-DD"}, {"name": "priority", "label": "Приоритет", "type": "select", "options": _ru_options(["low", "medium", "high"], PRIORITY_LABELS)[1:], "value": _ru("medium")},
        ], self.save_task)

    def save_task(self, values):
        client = next(c for c in repositories.get_clients_for_user(self.state.current_user) if c.name == values["client"])
        project = next((p for p in repositories.get_projects_for_user(self.state.current_user) if p.title == values["project"]), None)
        assignee = repositories.get_user_by_login(values["assignee"])
        repositories.create_task(self.state.current_user, client.id, project.id if project else None, values["title"], values["description"], assignee.id if assignee else None, _parse_date(values["due"]), _code_from_ru(values["priority"], PRIORITY_LABELS))
        self.toast("Задача создана")

    def open_task_status_modal(self, task):
        self.open_modal("Изменить статус", [{"name": "status", "label": "Статус", "type": "select", "options": _ru_options(["open", "in_progress", "blocked", "done", "overdue", "cancelled"], STATUS_LABELS)[1:], "value": _ru(task.status)}], lambda values: self.save_action(lambda: repositories.update_task_status(self.state.current_user, task.id, _code_from_ru(values["status"], STATUS_LABELS)), "Статус обновлён"))

    def open_task_due_modal(self, task):
        self.open_modal("Изменить срок", [{"name": "due", "label": "Срок YYYY-MM-DD", "value": _fmt(task.due_date)}], lambda values: self.save_action(lambda: repositories.update_task_due_date(self.state.current_user, task.id, _parse_date(values["due"])), "Срок обновлён"))

    def open_task_assignee_modal(self, task):
        users = repositories.get_users()
        current = next((u.login for u in users if u.id == task.assignee_user_id), users[0].login if users else "")
        self.open_modal("Сменить исполнителя", [{"name": "assignee", "label": "Исполнитель", "type": "select", "options": [u.login for u in users], "value": current}], lambda values: self.save_action(lambda: repositories.update_task_assignee(self.state.current_user, task.id, repositories.get_user_by_login(values["assignee"]).id), "Исполнитель обновлён"))

    def open_task_comment_modal(self, task):
        self.open_modal("Добавить комментарий", [{"name": "text", "label": "Комментарий", "type": "multiline", "height": 130}], lambda values: self.save_action(lambda: repositories.add_task_comment(self.state.current_user, task.id, values["text"]), "Комментарий добавлен"))

    def open_deal_modal(self):
        clients = repositories.get_clients_for_user(self.state.current_user)
        projects = repositories.get_projects_for_user(self.state.current_user)
        self.open_modal("Создать сделку", [
            {"name": "client", "label": "Клиент", "type": "select", "options": [c.name for c in clients], "value": clients[0].name if clients else ""},
            {"name": "project", "label": "Проект", "type": "select", "options": [""] + [p.title for p in projects], "value": ""},
            {"name": "name", "label": "Сделка"}, {"name": "stage", "label": "Этап", "type": "select", "options": _ru_options(["new", "qualification", "proposal", "negotiation", "contract", "won", "lost"], STAGE_LABELS)[1:], "value": _ru("new")}, {"name": "amount", "label": "Сумма", "value": "0"},
            {"name": "probability", "label": "Вероятность", "value": "10"}, {"name": "offer", "label": "КП есть", "type": "checkbox", "value": False},
            {"name": "last", "label": "Последняя активность YYYY-MM-DD"}, {"name": "status", "label": "Статус", "type": "select", "options": _ru_options(["active", "closed"], STATUS_LABELS)[1:], "value": _ru("active")},
        ], self.save_deal)

    def save_deal(self, values):
        client = next(c for c in repositories.get_clients_for_user(self.state.current_user) if c.name == values["client"])
        project = next((p for p in repositories.get_projects_for_user(self.state.current_user) if p.title == values["project"]), None)
        repositories.create_deal(self.state.current_user, client.id, project.id if project else None, values["name"], _code_from_ru(values["stage"], STAGE_LABELS), float(values["amount"]), int(values["probability"]), values["offer"], _parse_date(values["last"]), _code_from_ru(values["status"], STATUS_LABELS))
        self.toast("Сделка создана")

    def open_deal_field_modal(self, deal, field):
        label = {"stage": "Этап", "probability": "Вероятность", "status": "Статус"}[field]
        value = getattr(deal, field)
        if field == "stage":
            field_def = {"name": field, "label": label, "type": "select", "options": _ru_options(["new", "qualification", "proposal", "negotiation", "contract", "won", "lost"], STAGE_LABELS)[1:], "value": _ru(value)}
        elif field == "status":
            field_def = {"name": field, "label": label, "type": "select", "options": _ru_options(["active", "closed"], STATUS_LABELS)[1:], "value": _ru(value)}
        else:
            field_def = {"name": field, "label": label, "value": value}
        self.open_modal(label, [field_def], lambda values, field=field: self.save_deal_field(deal, field, values[field]))

    def save_deal_field(self, deal, field, value):
        if field == "stage":
            repositories.update_deal_stage(self.state.current_user, deal.id, _code_from_ru(value, STAGE_LABELS))
        elif field == "probability":
            repositories.update_deal_probability(self.state.current_user, deal.id, int(value))
        else:
            with get_session() as session:
                item = session.get(Deal, deal.id)
                item.status = _code_from_ru(value, STATUS_LABELS)
        self.toast("Сделка обновлена")

    def open_meeting_modal(self):
        clients = repositories.get_clients_for_user(self.state.current_user)
        self.open_modal("Создать встречу", [
            {"name": "client", "label": "Клиент", "type": "select", "options": [c.name for c in clients], "value": clients[0].name if clients else ""},
            {"name": "title", "label": "Тема"}, {"name": "when", "label": "Дата/время YYYY-MM-DD HH:MM"},
            {"name": "duration", "label": "Длительность", "value": "60"}, {"name": "participants", "label": "Участники"}, {"name": "agenda", "label": "Повестка", "type": "multiline", "height": 88},
        ], self.save_meeting)

    def save_meeting(self, values):
        client = next(c for c in repositories.get_clients_for_user(self.state.current_user) if c.name == values["client"])
        repositories.create_meeting(self.state.current_user, client.id, values["title"], _parse_datetime(values["when"]), int(values["duration"]), values["participants"], values["agenda"])
        self.toast("Встреча создана")

    def open_meeting_status_modal(self, meeting):
        self.open_modal("Статус встречи", [{"name": "status", "label": "Статус", "type": "select", "options": _ru_options(["planned", "completed", "cancelled"], STATUS_LABELS)[1:], "value": _ru(meeting.status)}], lambda values: self.save_action(lambda: repositories.update_meeting_status(self.state.current_user, meeting.id, _code_from_ru(values["status"], STATUS_LABELS)), "Статус встречи обновлён"))

    def open_meeting_summary_modal(self, meeting):
        self.open_modal("Итоги встречи", [{"name": "summary", "label": "Итоги", "value": meeting.summary or "", "type": "multiline", "height": 130}, {"name": "next", "label": "Следующие шаги", "value": meeting.next_steps or "", "type": "multiline", "height": 130}], lambda values: self.save_action(lambda: repositories.update_meeting_summary(self.state.current_user, meeting.id, values["summary"], values["next"]), "Итоги сохранены"))

    def open_meeting_move_modal(self, meeting):
        self.open_modal("Перенести встречу", [{"name": "when", "label": "Дата/время YYYY-MM-DD HH:MM", "value": _fmt(meeting.meeting_datetime)}], lambda values: self.move_meeting(meeting, values["when"]))

    def move_meeting(self, meeting, when):
        with get_session() as session:
            item = session.get(Meeting, meeting.id)
            item.meeting_datetime = _parse_datetime(when)
        self.toast("Встреча перенесена")

    def open_metric_modal(self):
        clients = repositories.get_clients_for_user(self.state.current_user)
        current = self.state.filters.get("metric_client")
        self.open_modal("Добавить метрику", [
            {"name": "client", "label": "Клиент", "type": "select", "options": [c.name for c in clients], "value": current or (clients[0].name if clients else "")},
            {"name": "date", "label": "Дата YYYY-MM-DD"}, {"name": "plan", "label": "План", "value": "0"}, {"name": "fact", "label": "Факт", "value": "0"},
            {"name": "activity", "label": "Активность", "value": "0"}, {"name": "nps", "label": "NPS", "value": "0"}, {"name": "risk", "label": "Риск", "value": "0"}, {"name": "comment", "label": "Комментарий", "type": "multiline", "height": 88},
        ], self.save_metric)

    def save_metric(self, values):
        client = next(c for c in repositories.get_clients_for_user(self.state.current_user) if c.name == values["client"])
        repositories.create_metric(self.state.current_user, client.id, _parse_date(values["date"]), float(values["plan"]), float(values["fact"]), int(values["activity"]), int(values["nps"]), int(values["risk"]), values["comment"])
        self.toast("Метрика добавлена")

    def format_indicator_value(self, value, unit):
        if value is None:
            return ""
        number = float(value)
        text = f"{round(number):,}".replace(",", " ") if number.is_integer() else f"{number:,.1f}".replace(",", " ").replace(".", ",")
        if unit == "₽":
            return f"{text} ₽"
        if unit:
            return f"{text} {unit}"
        return text

    def format_completion(self, fact, plan):
        if fact is None or not plan:
            return ""
        return f"Выполнение {round(float(fact) / float(plan) * 100)}%"

    def generate_onepage(self, client):
        self.run_action(lambda: onepage_service.generate_and_save_onepage(client.id, use_gigachat=True), "Справка сформирована")

    def generate_client_pdf(self, client):
        try:
            path = client_report_service.generate_client_pdf(client.id)
            self.toast(f"PDF создан: {path.name}")
        except Exception as exc:
            self.toast(str(exc), "error")

    def open_client_projects(self, client):
        self.state.filters["project_client"] = client.name
        self.switch_tab("Проекты")

    def open_client_tasks(self, client):
        self.state.filters["task_client"] = client.name
        self.switch_tab("Задачи")

    def open_latest_onepage(self, client):
        snapshot = onepage_service.get_latest_onepage(client.id)
        if not snapshot:
            self.toast("Справка ещё не сформирована", "error")
            return
        self.open_modal("Справка клиента", [{"name": "text", "label": "Справка", "value": snapshot.summary_text, "type": "multiline", "height": 520}], lambda values: self.close_modal())

    def open_news_modal(self, client):
        self.open_modal("Добавить новость", [
            {"name": "date", "label": "Дата YYYY-MM-DD", "value": _fmt(date.today())},
            {"name": "title", "label": "Заголовок"},
            {"name": "summary", "label": "Краткое содержание", "type": "multiline", "height": 120},
            {"name": "impact", "label": "Влияние", "type": "select", "options": _ru_options(["positive", "neutral", "negative"], STATUS_LABELS)[1:], "value": _ru("neutral")},
            {"name": "source", "label": "Источник", "value": "ручной ввод"},
        ], lambda values, client=client: self.save_action(lambda: repositories.create_client_news(self.state.current_user, client.id, _parse_date(values["date"]), values["title"], values["summary"], _code_from_ru(values["impact"], STATUS_LABELS), values["source"]), "Новость добавлена"))

    def open_roadmap_step_modal(self, project):
        users = repositories.get_users()
        self.open_modal("Добавить этап", [
            {"name": "title", "label": "Этап"},
            {"name": "description", "label": "Описание", "type": "multiline", "height": 88},
            {"name": "start", "label": "План старт YYYY-MM-DD"},
            {"name": "end", "label": "План конец YYYY-MM-DD"},
            {"name": "owner", "label": "Ответственный", "type": "select", "options": [""] + [u.login for u in users], "value": ""},
            {"name": "order", "label": "Порядок", "value": str(len(repositories.get_roadmap_steps_by_project(project.id)) + 1)},
        ], lambda values, project=project: self.save_roadmap_step(project, values))

    def save_roadmap_step(self, project, values):
        owner = repositories.get_user_by_login(values["owner"]) if values.get("owner") else None
        repositories.create_roadmap_step(self.state.current_user, project.id, values["title"], values["description"], _parse_date(values["start"]), _parse_date(values["end"]), owner.id if owner else None, int(values["order"] or 0))
        self.toast("Этап добавлен")

    def open_roadmap_status_modal(self, project):
        steps = repositories.get_roadmap_steps_by_project(project.id)
        self.open_modal("Статус этапа", [
            {"name": "step", "label": "Этап", "type": "select", "options": [s.title for s in steps], "value": steps[0].title if steps else ""},
            {"name": "status", "label": "Статус", "type": "select", "options": _ru_options(["planned", "in_progress", "delayed", "done", "cancelled"], STATUS_LABELS)[1:], "value": _ru(steps[0].status if steps else "planned")},
            {"name": "end", "label": "План конец YYYY-MM-DD", "value": _fmt(steps[0].planned_end_date) if steps else ""},
        ], lambda values, project=project: self.save_roadmap_status(project, values))

    def save_roadmap_status(self, project, values):
        step = next(s for s in repositories.get_roadmap_steps_by_project(project.id) if s.title == values["step"])
        repositories.update_roadmap_step(self.state.current_user, step.id, {"status": _code_from_ru(values["status"], STATUS_LABELS), "planned_end_date": _parse_date(values["end"])})
        self.toast("Этап обновлён")

    def open_team_member_modal(self, project):
        users = repositories.get_users()
        self.open_modal("Добавить участника", [
            {"name": "role", "label": "Роль", "type": "select", "options": [_ru(role) for role in sorted(repositories.TEAM_ROLES)], "value": _ru("manager")},
            {"name": "user", "label": "Пользователь", "type": "select", "options": [""] + [u.login for u in users], "value": ""},
            {"name": "name", "label": "ФИО"},
        ], lambda values, project=project: self.save_team_member(project, values))

    def save_team_member(self, project, values):
        user = repositories.get_user_by_login(values["user"]) if values.get("user") else None
        full_name = values["name"] or (user.full_name if user else "")
        repositories.add_project_team_member(self.state.current_user, project.id, full_name, _code_from_ru(values["role"], ROLE_LABELS), user.id if user else None)
        self.toast("Участник добавлен")

    def open_team_replace_modal(self, project):
        team = repositories.get_project_team(project.id)
        users = repositories.get_users()
        self.open_modal("Заменить участника", [
            {"name": "member", "label": "Участник", "type": "select", "options": [f"{_ru(m.role)}: {m.full_name}" for m in team], "value": f"{_ru(team[0].role)}: {team[0].full_name}" if team else ""},
            {"name": "user", "label": "Новый пользователь", "type": "select", "options": [""] + [u.login for u in users], "value": ""},
            {"name": "name", "label": "Новое ФИО"},
        ], lambda values, project=project: self.save_team_replace(project, values))

    def save_team_replace(self, project, values):
        team = repositories.get_project_team(project.id)
        member = next(m for m in team if f"{_ru(m.role)}: {m.full_name}" == values["member"])
        user = repositories.get_user_by_login(values["user"]) if values.get("user") else None
        full_name = values["name"] or (user.full_name if user else member.full_name)
        repositories.update_project_team_member(self.state.current_user, member.id, {"user_id": user.id if user else None, "full_name": full_name, "status": "active"})
        self.toast("Участник заменён")

    def generate_meeting_brief(self, meeting):
        self.run_action(lambda: meeting_brief_service.generate_and_save_meeting_brief(meeting.id, use_gigachat=True), "Материалы сформированы")

    def open_latest_meeting_brief(self, meeting):
        brief = meeting_brief_service.get_latest_meeting_brief(meeting.id)
        if not brief:
            self.toast("Материалы ещё не сформированы", "error")
            return
        self.open_modal("Материалы к встрече", [{"name": "text", "label": "Материалы", "value": brief.brief_text, "type": "multiline", "height": 520}], lambda values: self.close_modal())

    def run_background_checks(self):
        self.run_action(background_jobs.run_all_background_checks, "Проверки выполнены")

    def generate_daily_digest(self):
        self.run_action(lambda: daily_digest_service.save_daily_digest(use_gigachat=True), "Ежедневная сводка сформирована")

    def open_event_modal(self):
        client = next((c for c in repositories.get_clients_for_user(self.state.current_user) if c.id == self.state.selected.get("client")), None)
        self.open_modal("Добавить событие", [
            {"name": "type", "label": "Тип", "value": "ручное"}, {"name": "title", "label": "Заголовок"}, {"name": "description", "label": "Описание", "type": "multiline", "height": 110},
            {"name": "impact", "label": "Влияние", "type": "select", "options": _ru_options(["positive", "neutral", "negative"], STATUS_LABELS)[1:], "value": _ru("neutral")},
        ], lambda values: self.save_action(lambda: repositories.create_client_event(self.state.current_user, client.id, values["type"], values["title"], values["description"], _code_from_ru(values["impact"], STATUS_LABELS)), "Событие добавлено"))

    def send_message(self, history):
        body = self.state.filters.get("message_body", "").strip()
        if not body:
            self.toast("Введите текст сообщения", "error")
            return
        receiver = None
        client_id = None
        if history:
            last = history[-1]
            client_id = last.client_id
            receiver = last.sender_user_id if last.sender_user_id != self.state.current_user.id else last.receiver_user_id
        if not receiver:
            users = [u for u in repositories.get_users() if u.id != self.state.current_user.id]
            receiver = users[0].id if users else self.state.current_user.id
        repositories.create_message(client_id, self.state.current_user.id, receiver, "chat", "Сообщение", body)
        self.state.filters["message_body"] = ""
        self.toast("Сообщение отправлено")

    def read_notification(self, notification):
        if notification:
            self.run_action(lambda: repositories.mark_notification_read(self.state.current_user, notification.id), "Уведомление прочитано")

    def open_notification_target(self, notification):
        if not notification:
            return
        if notification.task_id:
            self.state.active_tab = "Задачи"; self.state.selected["task"] = notification.task_id
        elif notification.meeting_id:
            self.state.active_tab = "Календарь"; self.state.selected["meeting"] = notification.meeting_id
        elif notification.client_id:
            self.state.active_tab = "Клиенты"; self.state.selected["client"] = notification.client_id
        self.state.notification_panel_open = False

    def calendar_today(self):
        today = date.today()
        self.state.week_start = today - timedelta(days=today.weekday())

    def shift_week(self, delta):
        self.state.week_start = self.state.week_start + timedelta(days=7 * delta)

    def select_template(self, name):
        self.state.selected_template = name
        self.state.template_preview = ""
        self.state.template_drafts.setdefault(name, load_template(name))

    def save_template(self):
        name = self.state.selected_template
        Path("templates", name).write_text(self.state.template_drafts.get(name, ""), encoding="utf-8")
        self.toast("Шаблон сохранён")

    def reset_template(self):
        name = self.state.selected_template
        self.state.template_drafts[name] = load_template(name)
        self.state.template_preview = ""
        self.toast("Изменения сброшены")

    def preview_template(self):
        name = self.state.selected_template
        Path("templates", name).write_text(self.state.template_drafts.get(name, ""), encoding="utf-8")
        context = {
            "client_name": "Тестовый клиент", "task_title": "Проверить статус", "assignee_name": "Менеджер", "due_date": "2026-07-08",
            "priority": "medium", "change_description": "Изменён срок", "meeting_datetime": "2026-07-08 10:00", "agenda": "План работ",
            "risks": "Нет данных", "recommendations": "Проверить карточку", "event_title": "Новое событие", "event_description": "Описание",
            "impact": "neutral", "meeting_title": "Рабочая встреча", "preparation_items": "Повестка и метрики", "owner": "Менеджер",
            "recommended_action": "Связаться", "risk_clients": "Нет данных", "overdue_tasks": "Нет данных", "upcoming_meetings": "Нет данных",
            "daily_recommendations": "Проверить уведомления",
        }
        try:
            self.state.template_preview = render_template(name, context)
        except Exception as exc:
            self.state.template_preview = str(exc)
