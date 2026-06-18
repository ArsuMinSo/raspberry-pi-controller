from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from frontend.api_client import ApiClient, ApiError


class SettingsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        padding: 1 2;
        background: $surface;
    }
    #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #current-path {
        color: $text-muted;
        margin-bottom: 1;
    }
    Input {
        margin-bottom: 1;
    }
    #buttons {
        layout: horizontal;
        height: auto;
        align: right middle;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api
        self._current_path = ""

    def compose(self) -> ComposeResult:
        with Static(id="dialog"):
            yield Label("Settings", id="title")
            yield Label("Loading…", id="current-path")
            yield Label("SSH private key path:")
            yield Input(placeholder="/home/pi_controller/.ssh/id_rsa", id="key-path")
            with Static(id="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self._load_settings()

    @work(thread=True)
    def _load_settings(self) -> None:
        try:
            data = self._api.get_settings()
            path = data.get("ssh", {}).get("private_key_path", "")
            self.app.call_from_thread(self._set_current_path, path)
        except ApiError as e:
            self.app.call_from_thread(
                self.query_one("#current-path", Label).update,
                f"[red]Could not load: {e}[/red]",
            )

    def _set_current_path(self, path: str) -> None:
        self._current_path = path
        self.query_one("#current-path", Label).update(f"Current: [bold]{path or '(none)'}[/bold]")
        self.query_one("#key-path", Input).value = path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            path = self.query_one("#key-path", Input).value.strip()
            if not path:
                self.notify("Path cannot be empty", severity="warning")
                return
            self._save_settings(path)

    @work(thread=True)
    def _save_settings(self, path: str) -> None:
        try:
            self._api.set_ssh_key_path(path)
            self.app.call_from_thread(self.dismiss, path)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")
