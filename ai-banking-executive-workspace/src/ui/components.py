from dataclasses import dataclass
from typing import Callable, List, Optional

import pygame

from src.ui.theme import COLORS, RADII, SPACING


UI_DEBUG_HITBOXES = False
UI_DEBUG_FOCUS = False


def _component_enabled(component):
    return getattr(component, "visible", True) and getattr(component, "enabled", True)


def ellipsize(text, font, width):
    value = "" if text is None else str(text)
    if font.size(value)[0] <= width:
        return value
    while len(value) > 1 and font.size(value + "...")[0] > width:
        value = value[:-1]
    return value + "..."


def draw_text(surface, font, text, pos, color=None):
    rendered = font.render(str(text), True, color or COLORS["text"])
    surface.blit(rendered, pos)
    return rendered.get_rect(topleft=pos)


def _draw_shadow(surface, rect, radius=None, color=None, offset=4):
    shadow = pygame.Surface((rect.width + 12, rect.height + 12), pygame.SRCALPHA)
    pygame.draw.rect(
        shadow,
        color or COLORS["shadow"],
        pygame.Rect(6, 6 + offset // 2, rect.width, rect.height),
        border_radius=radius or RADII["lg"],
    )
    surface.blit(shadow, (rect.x - 6, rect.y - 6))


def draw_badge(surface, font, text, rect, tone="neutral"):
    tones = {
        "success": (COLORS["success_soft"], COLORS["success"]),
        "warning": (COLORS["warning_soft"], COLORS["text"]),
        "danger": (COLORS["danger_soft"], COLORS["danger"]),
        "info": (COLORS["secondary_light"], COLORS["secondary"]),
        "primary": (COLORS["primary_light"], COLORS["primary"]),
        "neutral": (COLORS["surface_alt"], COLORS["muted"]),
    }
    bg, fg = tones.get(tone, tones["neutral"])
    pygame.draw.rect(surface, bg, rect, border_radius=RADII["pill"])
    rendered = font.render(ellipsize(text, font, rect.width - 16), True, fg)
    surface.blit(rendered, rendered.get_rect(center=rect.center))


def draw_panel(surface, rect, title=None, font=None, title_font=None):
    radius = RADII["lg"]
    _draw_shadow(surface, rect, radius=radius)
    pygame.draw.rect(surface, COLORS["surface"], rect, border_radius=radius)
    pygame.draw.rect(surface, COLORS["border"], rect, width=1, border_radius=radius)
    if title and font and title_font:
        draw_text(surface, title_font, title, (rect.x + SPACING["lg"], rect.y + SPACING["md"]), COLORS["text_primary"])
        pygame.draw.line(surface, COLORS["border"], (rect.x + 1, rect.y + 50), (rect.right - 1, rect.y + 50), 1)


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    on_click: Optional[Callable] = None
    active: bool = False
    disabled: bool = False
    z_index: int = 10
    visible: bool = True
    enabled: bool = True
    name: str = ""
    style: str = "primary"

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        is_disabled = self.disabled or not self.enabled
        hovered = self.rect.collidepoint(mouse_pos) and not is_disabled
        radius = RADII["md"]
        border = None
        if is_disabled:
            color = COLORS["disabled"]
            text_color = COLORS["muted"]
            border = COLORS["disabled"]
        elif self.style == "ghost":
            color = COLORS["primary_light"] if (hovered or self.active) else COLORS["surface"]
            text_color = COLORS["primary"] if not self.active else COLORS["primary_dark"]
            border = COLORS["primary"] if self.active else COLORS["border"]
        elif self.style == "secondary":
            color = COLORS["secondary"] if (hovered or self.active) else COLORS["secondary_light"]
            text_color = (255, 255, 255) if (hovered or self.active) else COLORS["secondary"]
            border = COLORS["secondary"] if not hovered else COLORS["secondary"]
        elif self.style == "danger":
            color = COLORS["danger"] if (hovered or self.active) else COLORS["danger_soft"]
            text_color = (255, 255, 255) if (hovered or self.active) else COLORS["danger"]
            border = COLORS["danger"] if not hovered else COLORS["danger"]
        elif self.active:
            color = COLORS["primary_dark"]
            text_color = (255, 255, 255)
            border = COLORS["primary_dark"]
        elif hovered:
            color = COLORS["primary_hover"]
            text_color = (255, 255, 255)
            border = COLORS["primary_hover"]
        else:
            color = COLORS["primary"]
            text_color = (255, 255, 255)
            border = COLORS["primary"]
        pygame.draw.rect(surface, color, self.rect, border_radius=radius)
        pygame.draw.rect(surface, border, self.rect, width=1, border_radius=radius)
        rendered = font.render(ellipsize(self.label, font, self.rect.width - 14), True, text_color)
        surface.blit(rendered, rendered.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if self.disabled or not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            if self.on_click:
                self.on_click()
            return True
        return False


@dataclass
class TextInput:
    rect: pygame.Rect
    value: str = ""
    placeholder: str = ""
    focused: bool = False
    on_enter: Optional[Callable] = None
    password: bool = False
    z_index: int = 20
    visible: bool = True
    enabled: bool = True
    name: str = ""
    cursor_pos: Optional[int] = None
    max_length: Optional[int] = None

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        if self.cursor_pos is None:
            self.cursor_pos = len(self.value)
        self.cursor_pos = max(0, min(self.cursor_pos, len(self.value)))
        pygame.draw.rect(surface, COLORS["surface"], self.rect, border_radius=RADII["md"])
        pygame.draw.rect(
            surface,
            COLORS["primary"] if self.focused else COLORS["border"],
            self.rect,
            width=2 if self.focused else 1,
            border_radius=RADII["md"],
        )
        visible = "*" * len(self.value) if self.password else self.value
        text_area = pygame.Rect(self.rect.x + 12, self.rect.y + 4, self.rect.width - 24, self.rect.height - 8)
        color = COLORS["text"] if visible else COLORS["muted"]
        display = self._visible_slice(visible, font, text_area.width)
        text_y = self.rect.y + (self.rect.height - font.get_height()) // 2
        draw_text(surface, font, display if visible else self.placeholder, (text_area.x, text_y), color)
        if self.focused and pygame.time.get_ticks() % 1000 < 520:
            prefix = self._visible_slice(visible[: self.cursor_pos], font, text_area.width)
            cursor_x = min(text_area.right, text_area.x + font.size(prefix)[0] + 1)
            pygame.draw.line(surface, COLORS["primary"], (cursor_x, self.rect.y + 8), (cursor_x, self.rect.bottom - 8), 1)

    def _visible_slice(self, value, font, width):
        if font.size(value)[0] <= width:
            return value
        clipped = value
        while clipped and font.size(clipped)[0] > width:
            clipped = clipped[1:]
        return clipped

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.focused = True
                self.cursor_pos = len(self.value)
                return True
            self.focused = False
            return False
        if event.type == pygame.KEYDOWN and self.focused:
            if self.cursor_pos is None:
                self.cursor_pos = len(self.value)
            if event.key == pygame.K_BACKSPACE:
                if self.cursor_pos > 0:
                    self.value = self.value[: self.cursor_pos - 1] + self.value[self.cursor_pos :]
                    self.cursor_pos -= 1
            elif event.key == pygame.K_DELETE:
                if self.cursor_pos < len(self.value):
                    self.value = self.value[: self.cursor_pos] + self.value[self.cursor_pos + 1 :]
            elif event.key == pygame.K_LEFT:
                self.cursor_pos = max(0, self.cursor_pos - 1)
            elif event.key == pygame.K_RIGHT:
                self.cursor_pos = min(len(self.value), self.cursor_pos + 1)
            elif event.key == pygame.K_HOME:
                self.cursor_pos = 0
            elif event.key == pygame.K_END:
                self.cursor_pos = len(self.value)
            elif event.key == pygame.K_RETURN:
                if self.on_enter:
                    self.on_enter()
            elif event.key == pygame.K_ESCAPE:
                self.focused = False
            elif event.unicode:
                if self.max_length is None or len(self.value) < self.max_length:
                    self.value = self.value[: self.cursor_pos] + event.unicode + self.value[self.cursor_pos :]
                    self.cursor_pos += len(event.unicode)
            return True
        return False


class MultiLineTextInput(TextInput):
    def __init__(self, rect, value="", placeholder="", focused=False, on_enter=None):
        super().__init__(rect, value, placeholder, focused, on_enter)
        self.scroll_line = 0
        self.z_index = 20

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        if self.cursor_pos is None:
            self.cursor_pos = len(self.value)
        self.cursor_pos = max(0, min(self.cursor_pos, len(self.value)))
        pygame.draw.rect(surface, COLORS["surface"], self.rect, border_radius=RADII["md"])
        pygame.draw.rect(
            surface,
            COLORS["primary"] if self.focused else COLORS["border"],
            self.rect,
            width=2 if self.focused else 1,
            border_radius=RADII["md"],
        )
        inner = pygame.Rect(self.rect.x + 12, self.rect.y + 10, self.rect.width - 24, self.rect.height - 20)
        lines = self.value.splitlines() or [""]
        visible_count = max(1, inner.height // (font.get_height() + 4))
        cursor_line = self.value[: self.cursor_pos].count("\n")
        if cursor_line < self.scroll_line:
            self.scroll_line = cursor_line
        elif cursor_line >= self.scroll_line + visible_count:
            self.scroll_line = cursor_line - visible_count + 1
        self.scroll_line = max(0, min(self.scroll_line, max(0, len(lines) - visible_count)))
        if not self.value:
            draw_text(surface, font, self.placeholder, (inner.x, inner.y), COLORS["muted"])
        y = inner.y
        for line in lines[self.scroll_line : self.scroll_line + visible_count]:
            draw_text(surface, font, ellipsize(line, font, inner.width), (inner.x, y), COLORS["text"])
            y += font.get_height() + 4
        if self.focused and pygame.time.get_ticks() % 1000 < 520:
            before = self.value[: self.cursor_pos]
            cursor_line = before.count("\n")
            cursor_col = len(before.split("\n")[-1])
            if self.scroll_line <= cursor_line < self.scroll_line + visible_count:
                line_value = lines[cursor_line] if cursor_line < len(lines) else ""
                prefix = ellipsize(line_value[:cursor_col], font, inner.width)
                cursor_x = min(inner.right, inner.x + font.size(prefix)[0] + 1)
                cursor_y = inner.y + (cursor_line - self.scroll_line) * (font.get_height() + 4)
                pygame.draw.line(surface, COLORS["primary"], (cursor_x, cursor_y), (cursor_x, cursor_y + font.get_height()), 1)

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.focused = True
                self.cursor_pos = len(self.value)
                return True
            self.focused = False
            return False
        if event.type == pygame.MOUSEWHEEL and self.focused:
            self.scroll_line = max(0, self.scroll_line - event.y)
            return True
        if event.type == pygame.KEYDOWN and self.focused:
            if self.cursor_pos is None:
                self.cursor_pos = len(self.value)
            if event.key == pygame.K_RETURN:
                if pygame.key.get_mods() & pygame.KMOD_CTRL:
                    if self.on_enter:
                        self.on_enter()
                else:
                    self.value = self.value[: self.cursor_pos] + "\n" + self.value[self.cursor_pos :]
                    self.cursor_pos += 1
                return True
            return super().handle_event(event)
        return False


class PasswordInput(TextInput):
    def __init__(self, rect, value="", placeholder="", focused=False, on_enter=None):
        super().__init__(rect, value, placeholder, focused, on_enter, password=True)


@dataclass
class SelectBox:
    rect: pygame.Rect
    options: List[str]
    value: str = ""
    opened: bool = False
    on_change: Optional[Callable] = None
    z_index: int = 20
    visible: bool = True
    enabled: bool = True
    name: str = ""
    scroll_offset: int = 0
    max_visible: int = 7

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        pygame.draw.rect(surface, COLORS["surface"], self.rect, border_radius=RADII["md"])
        pygame.draw.rect(
            surface,
            COLORS["primary"] if self.opened else COLORS["border"],
            self.rect,
            width=2 if self.opened else 1,
            border_radius=RADII["md"],
        )
        label = self.value or (self.options[0] if self.options else "")
        draw_text(surface, font, ellipsize(label, font, self.rect.width - 34), (self.rect.x + 12, self.rect.y + 9))
        draw_text(surface, font, "v", (self.rect.right - 20, self.rect.y + 9), COLORS["muted"])

    def dropdown_rect(self):
        visible_count = min(len(self.options), self.max_visible)
        return pygame.Rect(self.rect.x, self.rect.bottom + 3, self.rect.width, visible_count * self.rect.height)

    def draw_dropdown(self, surface, font, mouse_pos):
        if not self.opened or not self.visible:
            return
        visible_count = min(len(self.options), self.max_visible)
        max_offset = max(0, len(self.options) - visible_count)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
        menu_rect = self.dropdown_rect()
        _draw_shadow(surface, menu_rect, radius=RADII["md"], color=COLORS["shadow"])
        pygame.draw.rect(surface, COLORS["surface"], menu_rect, border_radius=RADII["md"])
        pygame.draw.rect(surface, COLORS["border"], menu_rect, width=1, border_radius=RADII["md"])
        for local_idx, option in enumerate(self.options[self.scroll_offset : self.scroll_offset + visible_count]):
            opt_rect = pygame.Rect(self.rect.x, self.rect.bottom + 3 + local_idx * self.rect.height, self.rect.width, self.rect.height)
            pygame.draw.rect(surface, COLORS["surface_hover"] if opt_rect.collidepoint(mouse_pos) else COLORS["surface"], opt_rect)
            if option == self.value:
                pygame.draw.rect(surface, COLORS["selected"], opt_rect)
            pygame.draw.line(surface, COLORS["border"], (opt_rect.x + 8, opt_rect.bottom), (opt_rect.right - 8, opt_rect.bottom), 1)
            draw_text(surface, font, ellipsize(option, font, opt_rect.width - 18), (opt_rect.x + 9, opt_rect.y + 9))

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEWHEEL and self.opened and self.dropdown_rect().collidepoint(pygame.mouse.get_pos()):
            visible_count = min(len(self.options), self.max_visible)
            self.scroll_offset = max(0, min(self.scroll_offset - event.y, max(0, len(self.options) - visible_count)))
            return True
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        if self.rect.collidepoint(event.pos):
            self.opened = not self.opened
            return True
        if self.opened:
            visible_count = min(len(self.options), self.max_visible)
            for local_idx, option in enumerate(self.options[self.scroll_offset : self.scroll_offset + visible_count]):
                opt_rect = pygame.Rect(self.rect.x, self.rect.bottom + 3 + local_idx * self.rect.height, self.rect.width, self.rect.height)
                if opt_rect.collidepoint(event.pos):
                    self.value = option
                    self.opened = False
                    if self.on_change:
                        self.on_change(option)
                    return True
            self.opened = False
            return True
        return False


@dataclass
class Checkbox:
    rect: pygame.Rect
    checked: bool = False
    label: str = ""
    on_change: Optional[Callable] = None
    z_index: int = 20
    visible: bool = True
    enabled: bool = True
    name: str = ""

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        box = pygame.Rect(self.rect.x, self.rect.y + 4, 18, 18)
        pygame.draw.rect(surface, COLORS["surface"], box, border_radius=RADII["sm"])
        pygame.draw.rect(surface, COLORS["primary"], box, width=2, border_radius=RADII["sm"])
        if self.checked:
            pygame.draw.line(surface, COLORS["primary"], (box.x + 4, box.y + 9), (box.x + 8, box.y + 14), 2)
            pygame.draw.line(surface, COLORS["primary"], (box.x + 8, box.y + 14), (box.x + 15, box.y + 4), 2)
        if self.label:
            draw_text(surface, font, self.label, (self.rect.x + 26, self.rect.y + 2))

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self.checked = not self.checked
            if self.on_change:
                self.on_change(self.checked)
            return True
        return False


@dataclass
class ScrollableTable:
    rect: pygame.Rect
    columns: List[dict]
    rows: List[dict]
    scroll_offset: int = 0
    selected_row_id: Optional[str] = None
    on_row_click: Optional[Callable] = None
    on_row_double_click: Optional[Callable] = None
    row_height: int = 34
    header_height: int = 34
    z_index: int = 5
    visible: bool = True
    enabled: bool = True
    name: str = ""

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        draw_panel(surface, self.rect)
        header_rect = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.header_height)
        pygame.draw.rect(surface, COLORS["table_header"], header_rect, border_top_left_radius=RADII["lg"], border_top_right_radius=RADII["lg"])
        x = self.rect.x
        for col in self.columns:
            width = col["width"]
            draw_text(surface, font, ellipsize(col["title"], font, width - 12), (x + 8, self.rect.y + 8), COLORS["muted"])
            x += width
        pygame.draw.line(surface, COLORS["border"], (self.rect.x, self.rect.y + self.header_height), (self.rect.right, self.rect.y + self.header_height), 1)

        visible_count = max(1, (self.rect.height - self.header_height) // self.row_height)
        max_offset = max(0, len(self.rows) - visible_count)
        self.scroll_offset = min(max(0, self.scroll_offset), max_offset)
        visible = self.rows[self.scroll_offset : self.scroll_offset + visible_count]
        if not visible:
            draw_text(surface, font, self.empty_text(), (self.rect.x + 14, self.rect.y + self.header_height + 14), COLORS["muted"])
            return

        for idx, row in enumerate(visible):
            y = self.rect.y + self.header_height + idx * self.row_height
            row_rect = pygame.Rect(self.rect.x + 8, y + 2, self.rect.width - 16, self.row_height - 4)
            row_id = row.get("id")
            base = row.get("_bg") or (COLORS["table_zebra"] if (idx + self.scroll_offset) % 2 == 0 else COLORS["surface"])
            if row_id == self.selected_row_id:
                base = COLORS["selected"]
            elif row_rect.collidepoint(mouse_pos):
                base = COLORS["surface_hover"]
            pygame.draw.rect(surface, base, row_rect, border_radius=RADII["sm"])
            x = self.rect.x
            for col in self.columns:
                width = col["width"]
                value = row.get(col["key"], "")
                draw_text(surface, font, ellipsize(value, font, width - 12), (x + 8, y + 8), COLORS["text"])
                x += width
            pygame.draw.line(surface, COLORS["border"], (self.rect.x + 12, row_rect.bottom + 2), (self.rect.right - 12, row_rect.bottom + 2), 1)

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self.rect.collidepoint(mouse_pos):
                self.scroll_offset -= event.y
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            y = event.pos[1] - self.rect.y - self.header_height
            if y >= 0:
                index = self.scroll_offset + y // self.row_height
                if 0 <= index < len(self.rows):
                    row = self.rows[index]
                    self.selected_row_id = row.get("id")
                    if getattr(event, "clicks", 1) >= 2 and self.on_row_double_click:
                        self.on_row_double_click(row)
                    elif self.on_row_click:
                        self.on_row_click(row)
                    return True
        return False

    def empty_text(self):
        name = self.name or ""
        if "task" in name:
            return "Нет задач"
        if "meeting" in name or "calendar" in name:
            return "Нет встреч"
        if "notification" in name or "notif" in name:
            return "Нет уведомлений"
        if "message" in name:
            return "Нет сообщений"
        return "Нет данных"


@dataclass
class ScrollableList:
    rect: pygame.Rect
    rows: List[dict]
    scroll_offset: int = 0
    selected_row_id: Optional[str] = None
    on_row_click: Optional[Callable] = None
    row_height: int = 58
    z_index: int = 5
    visible: bool = True
    enabled: bool = True
    name: str = ""

    def draw(self, surface, font, small_font, mouse_pos):
        if not self.visible:
            return
        draw_panel(surface, self.rect)
        visible_count = max(1, self.rect.height // self.row_height)
        self.scroll_offset = min(max(0, self.scroll_offset), max(0, len(self.rows) - visible_count))
        visible = self.rows[self.scroll_offset : self.scroll_offset + visible_count]
        if not visible:
            draw_text(surface, font, self.empty_text(), (self.rect.x + 14, self.rect.y + 14), COLORS["muted"])
            return
        for idx, row in enumerate(visible):
            y = self.rect.y + idx * self.row_height
            row_rect = pygame.Rect(self.rect.x + 8, y + 4, self.rect.width - 16, self.row_height - 8)
            color = COLORS["selected"] if row.get("id") == self.selected_row_id else (COLORS["surface_hover"] if row_rect.collidepoint(mouse_pos) else COLORS["surface"])
            pygame.draw.rect(surface, color, row_rect, border_radius=RADII["md"])
            draw_text(surface, font, ellipsize(row.get("title", ""), font, self.rect.width - 34), (self.rect.x + 16, y + 10))
            draw_text(surface, small_font, ellipsize(row.get("subtitle", ""), small_font, self.rect.width - 34), (self.rect.x + 16, y + 32), COLORS["muted"])

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll_offset -= event.y
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            index = self.scroll_offset + (event.pos[1] - self.rect.y) // self.row_height
            if 0 <= index < len(self.rows):
                row = self.rows[index]
                self.selected_row_id = row.get("id")
                if self.on_row_click:
                    self.on_row_click(row)
                return True
        return False

    def empty_text(self):
        name = self.name or ""
        if "dialog" in name or "message" in name:
            return "Нет сообщений"
        if "notification" in name or "notif" in name:
            return "Нет уведомлений"
        if "task" in name:
            return "Нет задач"
        return "Нет данных"


@dataclass
class Modal:
    title: str
    fields: list
    on_save: Callable
    on_cancel: Callable
    error: str = ""

    def draw(self, surface, fonts, mouse_pos, widgets):
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((31, 41, 51, 74))
        surface.blit(overlay, (0, 0))
        rect = pygame.Rect(260, 60, 660, 700)
        draw_panel(surface, rect, self.title, fonts["normal"], fonts["subtitle"])
        for widget in widgets:
            widget.draw(surface, fonts["normal"], mouse_pos)
        if self.error:
            draw_text(surface, fonts["small"], self.error, (rect.x + 20, rect.bottom - 74), COLORS["danger"])


@dataclass
class Toast:
    message: str
    kind: str = "success"
    ttl: int = 120

    def draw(self, surface, font):
        width = min(430, max(220, font.size(self.message)[0] + 34))
        rect = pygame.Rect(surface.get_width() - width - 18, surface.get_height() - 58, width, 40)
        color = COLORS["success"] if self.kind == "success" else COLORS["danger"]
        _draw_shadow(surface, rect, radius=RADII["md"], color=COLORS["shadow_strong"], offset=2)
        pygame.draw.rect(surface, color, rect, border_radius=RADII["md"])
        draw_text(surface, font, ellipsize(self.message, font, rect.width - 22), (rect.x + 12, rect.y + 10), (255, 255, 255))


@dataclass
class NotificationBell:
    rect: pygame.Rect
    count: int
    on_click: Optional[Callable] = None
    z_index: int = 100
    visible: bool = True
    enabled: bool = True
    name: str = "notification_bell"

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        color = COLORS["primary_hover"] if self.rect.collidepoint(mouse_pos) else COLORS["primary"]
        pygame.draw.rect(surface, color, self.rect, border_radius=RADII["md"])
        cx = self.rect.x + 20
        cy = self.rect.centery + 1
        points = [
            (cx - 8, cy + 3),
            (cx - 8, cy - 1),
            (cx - 6, cy - 6),
            (cx - 2, cy - 9),
            (cx + 2, cy - 9),
            (cx + 6, cy - 6),
            (cx + 8, cy - 1),
            (cx + 8, cy + 3),
        ]
        pygame.draw.lines(surface, (255, 255, 255), False, points, 2)
        pygame.draw.line(surface, (255, 255, 255), (cx - 10, cy + 4), (cx + 10, cy + 4), 2)
        pygame.draw.circle(surface, (255, 255, 255), (cx, cy + 7), 2)
        pygame.draw.line(surface, (255, 255, 255), (cx, cy - 11), (cx, cy - 9), 2)
        if self.count > 0:
            badge_text = "9+" if self.count > 9 else str(self.count)
            badge = pygame.Rect(self.rect.right - 28, self.rect.y + 7, 22, 20)
            pygame.draw.rect(surface, COLORS["danger"], badge, border_radius=RADII["pill"])
            badge_rendered = font.render(badge_text, True, (255, 255, 255))
            surface.blit(badge_rendered, badge_rendered.get_rect(center=badge.center))

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            if self.on_click:
                self.on_click()
            return True
        return False


@dataclass
class AssistantFloatingButton:
    rect: pygame.Rect
    has_alerts: bool = False
    on_click: Optional[Callable] = None
    z_index: int = 180
    visible: bool = True
    enabled: bool = True
    name: str = "assistant_button"

    def draw(self, surface, font, mouse_pos):
        if not self.visible:
            return
        hovered = self.rect.collidepoint(mouse_pos)
        color = COLORS["primary_hover"] if hovered else COLORS["primary"]
        _draw_shadow(surface, self.rect, radius=RADII["xl"], color=COLORS["shadow_strong"], offset=3)
        pygame.draw.rect(surface, color, self.rect, border_radius=RADII["xl"])
        pygame.draw.rect(surface, COLORS["primary_dark"], self.rect, width=1, border_radius=RADII["xl"])
        rendered = font.render("AI", True, (255, 255, 255))
        surface.blit(rendered, rendered.get_rect(center=self.rect.center))
        if self.has_alerts:
            indicator = pygame.Rect(self.rect.right - 12, self.rect.y + 4, 10, 10)
            pygame.draw.ellipse(surface, COLORS["danger"], indicator)

    def handle_event(self, event):
        if not _component_enabled(self):
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            if self.on_click:
                self.on_click()
            return True
        return False


class AssistantChatPanel:
    def __init__(self, rect):
        self.rect = rect

    def draw(self, surface, fonts, mouse_pos, history, status="", context_text=""):
        radius = RADII["lg"]
        _draw_shadow(surface, self.rect, radius=radius, color=COLORS["shadow_strong"], offset=4)
        pygame.draw.rect(surface, COLORS["surface"], self.rect, border_radius=radius)
        pygame.draw.rect(surface, COLORS["border"], self.rect, width=1, border_radius=radius)
        header = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, 58)
        pygame.draw.rect(surface, COLORS["primary"], header, border_top_left_radius=radius, border_top_right_radius=radius)
        draw_text(surface, fonts["subtitle"], "AI-ассистент", (header.x + 16, header.y + 16), (255, 255, 255))
        if status:
            draw_text(surface, fonts["small"], status, (header.x + 170, header.y + 19), (232, 248, 236))
        history_rect = pygame.Rect(self.rect.x + 16, self.rect.y + 72, self.rect.width - 32, 308)
        pygame.draw.rect(surface, COLORS["surface_muted"], history_rect, border_radius=RADII["md"])
        pygame.draw.rect(surface, COLORS["border"], history_rect, width=1, border_radius=RADII["md"])
        if not history:
            draw_text(surface, fonts["small"], "Задайте вопрос по клиентам, рискам, задачам или сделкам.", (history_rect.x + 12, history_rect.y + 12), COLORS["muted"])

        # Keep the latest messages visible and reserve space for the role label,
        # message text and bottom padding inside every bubble.
        visible_messages = []
        used_height = 0
        available_height = history_rect.height - 24
        for item in reversed(history[-6:]):
            role = item.get("role", "")
            text_value = item.get("text", "")
            if item.get("pending"):
                dots = "." * ((pygame.time.get_ticks() // 400) % 4)
                text_value = f"{text_value}{dots}"
            lines = _wrap_text(text_value, fonts["small"], history_rect.width - 96)[:4]
            bubble_h = 34 + len(lines) * 20
            item_height = bubble_h + (8 if visible_messages else 0)
            if used_height + item_height > available_height:
                break
            visible_messages.append((item, role, lines, bubble_h))
            used_height += item_height

        y = history_rect.y + 12
        for item, role, lines, bubble_h in reversed(visible_messages):
            bubble_w = min(history_rect.width - 34, max(120, max(fonts["small"].size(line)[0] for line in lines) + 24))
            bubble_x = history_rect.right - bubble_w - 14 if role == "user" else history_rect.x + 12
            bubble = pygame.Rect(bubble_x, y, bubble_w, bubble_h)
            bubble_bg = COLORS["chat_out"] if role == "user" else COLORS["surface"]
            bubble_fg = COLORS["primary_dark"] if role == "user" else COLORS["text"]
            pygame.draw.rect(surface, bubble_bg, bubble, border_radius=RADII["md"])
            pygame.draw.rect(surface, COLORS["border"], bubble, width=1, border_radius=RADII["md"])
            label = "Вы" if role == "user" else "AI"
            draw_text(surface, fonts["small"], label, (bubble.x + 12, bubble.y + 8), COLORS["muted"])
            line_y = bubble.y + 28
            for line in lines:
                draw_text(surface, fonts["small"], line, (bubble.x + 12, line_y), bubble_fg)
                line_y += 20
            y += bubble_h + 8
        if context_text:
            context_rect = pygame.Rect(self.rect.x + 16, self.rect.bottom - 92, self.rect.width - 32, 48)
            pygame.draw.rect(surface, COLORS["primary_light"], context_rect, border_radius=RADII["md"])
            pygame.draw.rect(surface, COLORS["border"], context_rect, width=1, border_radius=RADII["md"])
            draw_text(surface, fonts["small"], ellipsize(context_text, fonts["small"], context_rect.width - 24), (context_rect.x + 12, context_rect.y + 14), COLORS["primary_dark"])
        if UI_DEBUG_FOCUS:
            pygame.draw.rect(surface, COLORS["danger"], self.rect, 2, border_radius=radius)


def _wrap_text(text, font, width):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        # Split unbroken tokens such as a URL or an identifier so they cannot
        # extend beyond the chat bubble.
        while font.size(word)[0] > width:
            prefix = word
            while len(prefix) > 1 and font.size(prefix)[0] > width:
                prefix = prefix[:-1]
            lines.append(prefix)
            word = word[len(prefix):]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


class SearchBox(TextInput):
    pass
