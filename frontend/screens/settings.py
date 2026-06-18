from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from frontend.api_client import ApiClient, ApiError


class SettingsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    #dialog {
        width: 72;
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
    .section-header {
        text-style: bold;
        color: $accent;
        margin-top: 1;
    }
    .field-label {
        margin-top: 1;
    }
    .row {
        layout: horizontal;
        height: auto;
    }
    .row Input {
        width: 1fr;
        margin-right: 1;
    }
    .row Input:last-child {
        margin-right: 0;
    }
    Input {
        margin-bottom: 0;
    }
    #test-result {
        margin-top: 1;
        padding: 0 1;
        height: auto;
        min-height: 3;
        border: solid $panel;
        background: $panel;
        color: $text;
    }
    #buttons-save {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #buttons-test {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #buttons-close {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api

    def compose(self) -> ComposeResult:
        with Static(id="dialog"):
            yield Label("SSH Settings & Diagnostics", id="title")

            yield Label("── SSH Configuration ──────────────────────────────────", classes="section-header")
            yield Label("Private key path:", classes="field-label")
            yield Input(placeholder="/home/pi_controller/.ssh/id_rsa", id="key-path")
            with Static(classes="row"):
                yield Input(placeholder="Username (e.g. pi)", id="username")
                yield Input(placeholder="Timeout s (e.g. 30)", id="timeout")
            with Static(id="buttons-save"):
                yield Button("Save SSH Settings", variant="primary", id="save")

            yield Label("── Test Connection ────────────────────────────────────", classes="section-header")
            yield Label("Target IP address:", classes="field-label")
            yield Input(placeholder="10.10.20.x", id="test-ip")
            with Static(id="buttons-test"):
                yield Button("Test SSH", variant="default", id="test")
            yield Static("Press [Test SSH] to diagnose a connection.", id="test-result")

            with Static(id="buttons-close"):
                yield Button("Close", variant="default", id="close")

    def on_mount(self) -> None:
        self._load_settings()

    @work(thread=True)
    def _load_settings(self) -> None:
        try:
            data = self._api.get_settings()
            ssh = data.get("ssh", {})
            self.app.call_from_thread(self._populate, ssh)
        except ApiError as e:
            self.app.call_from_thread(
                self._set_result, f"[red]Could not load settings: {e}[/red]"
            )

    def _populate(self, ssh: dict) -> None:
        self.query_one("#key-path", Input).value = ssh.get("private_key_path") or ""
        self.query_one("#username", Input).value = ssh.get("username") or ""
        self.query_one("#timeout", Input).value = str(ssh.get("timeout_s") or "")

    def _set_result(self, markup: str) -> None:
        self.query_one("#test-result", Static).update(markup)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "save":
            self._do_save()
        elif event.button.id == "test":
            ip = self.query_one("#test-ip", Input).value.strip()
            if not ip:
                self.notify("Enter a target IP first", severity="warning")
                return
            self._set_result("[yellow]Connecting…[/yellow]")
            self._do_test(ip)

    def _do_save(self) -> None:
        key_path = self.query_one("#key-path", Input).value.strip() or None
        username = self.query_one("#username", Input).value.strip() or None
        timeout_raw = self.query_one("#timeout", Input).value.strip()
        timeout_s: int | None = None
        if timeout_raw:
            try:
                timeout_s = int(timeout_raw)
            except ValueError:
                self.notify("Timeout must be a number", severity="warning")
                return
        self._save_settings(key_path, username, timeout_s)

    @work(thread=True)
    def _save_settings(self, key_path, username, timeout_s) -> None:
        try:
            self._api.update_ssh_settings(key_path=key_path, username=username, timeout_s=timeout_s)
            self.app.call_from_thread(self.notify, "SSH settings saved")
            self.app.call_from_thread(self._load_settings)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_test(self, ip: str) -> None:
        try:
            r = self._api.test_ssh_connection(ip)
        except ApiError as e:
            self.app.call_from_thread(self._set_result, f"[red]Request failed: {e}[/red]")
            return

        used = r.get("settings_used", {})
        header = (
            f"key=[bold]{used.get('private_key_path', '?')}[/bold]  "
            f"user=[bold]{used.get('username', '?')}[/bold]  "
            f"timeout=[bold]{used.get('timeout_s', '?')}s[/bold]"
        )

        if r.get("success"):
            body = r.get("stdout") or ""
            markup = f"[green]SUCCESS[/green]  {header}\n{body}"
        else:
            etype = r.get("error_type", "")
            err = r.get("error", "unknown error")
            markup = f"[red]FAILED[/red] [{etype}]  {header}\n[red]{err}[/red]"

        self.app.call_from_thread(self._set_result, markup)
