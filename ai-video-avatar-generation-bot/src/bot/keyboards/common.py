from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def markup(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows])


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Create video", callback_data="menu:create")],
            [InlineKeyboardButton(text="My videos", callback_data="menu:history")],
        ]
    )


def navigation(back: str = "nav:back") -> list[list[tuple[str, str]]]:
    return [[("Back", back)], [("Main menu", "menu:main")]]


def back_main(back: str) -> InlineKeyboardMarkup:
    return markup(*navigation(back))


def video_types() -> InlineKeyboardMarkup:
    return markup([("Greeting", "type:greeting")], [("Team update", "type:meeting")], [("News", "type:news")], *navigation("menu:main"))


def avatar_keyboard(draft_id: int, index: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    if total > 1:
        rows.append([
            ("◀️ Previous", f"avatar:show:{draft_id}:{index}:{(index - 1) % total}"),
            ("Next ▶️", f"avatar:show:{draft_id}:{index}:{(index + 1) % total}"),
        ])
    rows.extend([
        [("✅ Select this avatar", f"avatar:choose:{draft_id}:{index}")],
        [("⬅️ Back", "nav:avatar_back"), ("🏠 Main menu", "menu:main")],
    ])
    return markup(*rows)


def source_choice() -> InlineKeyboardMarkup:
    return markup([("Enter text", "source:text")], [("Record voice", "source:voice")], *navigation("nav:avatar_back"))


def voice_confirmation_keyboard(target: str) -> InlineKeyboardMarkup:
    rows = [
        [("Confirm", "voice:confirm")],
        [("Record again", "voice:retry"), ("Edit as text", "voice:edit")],
    ]
    if target == "revision":
        rows.append([("Cancel changes", "voice:cancel")])
    rows.extend([[("Back", "voice:back")], [("Main menu", "menu:main")]])
    return markup(*rows)


def review_keyboard(draft_id: int, show_original: bool = False) -> InlineKeyboardMarkup:
    rows = [[("Confirm script", f"text:confirm:{draft_id}")], [("Write changes", f"text:edit:{draft_id}")], [("Record changes", f"text:voice:{draft_id}")], [("Generate again", f"text:regenerate:{draft_id}")]]
    if show_original: rows.append([("Restore original", f"text:original:{draft_id}")])
    rows.extend([[("Change avatar", f"avatar:edit:{draft_id}")], *navigation("nav:review_back")])
    return markup(*rows)


def final_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return markup([("Generate video", f"video:generate:{draft_id}")], [("Edit script", f"text:edit:{draft_id}")], [("Change avatar", f"avatar:edit:{draft_id}")], *navigation("nav:final_back"))


def history_item_keyboard(draft_id: int, index: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    if total > 1:
        rows.append([
            ("◀️", f"history:page:{(index - 1) % total}"),
            ("▶️", f"history:page:{(index + 1) % total}"),
        ])
    rows.extend([[("Open", f"history:open:{draft_id}")], [("Main menu", "menu:main")]])
    return markup(*rows)


def generation_status_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return markup([("Refresh status", f"history:refresh:{draft_id}")], [("My videos", "menu:history")], [("Main menu", "menu:main")])


def ready_video_keyboard(draft_id: int, has_url: bool) -> InlineKeyboardMarkup:
    rows = [[("Get video", f"history:get_video:{draft_id}")]]
    if has_url:
        rows.append([("Open link", f"history:link:{draft_id}")])
    rows.extend([[("My videos", "menu:history")], [("Main menu", "menu:main")]])
    return markup(*rows)


def error_video_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return markup(
        [("Return to generation", f"history:resume_error:{draft_id}")],
        [("Edit script", f"text:edit:{draft_id}")],
        [("Change avatar", f"avatar:edit:{draft_id}")],
        [("My videos", "menu:history")],
        [("Main menu", "menu:main")],
    )
