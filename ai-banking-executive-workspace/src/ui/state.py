from dataclasses import dataclass, field


@dataclass
class AppState:
    current_user: object = None
    active_tab: str = "Dashboard"
    selected_template: str = None
    login: str = ""
    password: str = ""
    focused_input: str = "login"
    focused_input_key: object = ("login", "login")
    open_select_key: object = None
    login_error: str = ""
    running: bool = True
    mouse_pos: tuple = (0, 0)
    inputs: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    scrolls: dict = field(default_factory=dict)
    selected: dict = field(default_factory=dict)
    modal: object = None
    modal_inputs: dict = field(default_factory=dict)
    modal_error: str = ""
    toasts: list = field(default_factory=list)
    notification_panel_open: bool = False
    notification_filter: str = "Все"
    sections_menu_open: bool = False
    assistant_open: bool = False
    assistant_question: str = ""
    assistant_history: list = field(default_factory=list)
    assistant_context: str = ""
    assistant_status: str = ""
    assistant_pending: bool = False
    assistant_voice_pending: bool = False
    assistant_voice_recording: bool = False
    assistant_request_id: int = 0
    assistant_pending_command: dict = field(default_factory=dict)
    week_start: object = None
    template_drafts: dict = field(default_factory=dict)
    template_preview: str = ""
    message_text: str = ""
    message_search: str = ""
