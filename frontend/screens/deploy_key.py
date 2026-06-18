from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from frontend.api_client import ApiClient, ApiError


class DeployKeyScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    DeployKeyScreen {
        align: center middle;
    }
    #dialog {
        width: 64;
        height: auto;
        border: thick $primary;
        padding: 1 2;
        background: $surface;
        layout: vertical;
    }
    #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #targets {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }
    #pwd-label {
        margin-top: 1;
    }
    Input {
        margin-bottom: 1;
    }
    #results-box {
        height: 12;
        border: solid $panel;
        background: $panel-darken-1;
        padding: 0 1;
        margin-top: 1;
    }
    #results-content {
        height: auto;
    }
    #buttons {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, api: ApiClient, positions: list[str]):
        super().__init__()
        self._api = api
        self._positions = positions

    def compose(self) -> ComposeResult:
        with Static(id="dialog"):
            yield Label("Deploy SSH Key", id="title")
            yield Label(
                f"Targets ({len(self._positions)}): {', '.join(self._positions)}",
                id="targets",
            )
            yield Label("SSH password for target Pi(s):", id="pwd-label")
            yield Input(password=True, placeholder="password", id="pwd-input")
            with ScrollableContainer(id="results-box"):
                yield Static(
                    "Enter password and press Deploy.", id="results-content"
                )
            with Static(id="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Deploy Key", variant="primary", id="deploy")

    def on_mount(self) -> None:
        self.query_one("#pwd-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "deploy":
            self._start_deploy()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._start_deploy()

    def _start_deploy(self) -> None:
        password = self.query_one("#pwd-input", Input).value
        if not password:
            self.notify("Enter password", severity="warning")
            return
        self.query_one("#deploy", Button).disabled = True
        self.query_one("#pwd-input", Input).disabled = True
        self.query_one("#results-content", Static).update("[yellow]Deploying…[/yellow]")
        self._do_deploy(password)

    @work(thread=True)
    def _do_deploy(self, password: str) -> None:
        try:
            data = self._api.deploy_key(self._positions, password)
            self.app.call_from_thread(self._show_results, data)
        except ApiError as e:
            self.app.call_from_thread(
                self.query_one("#results-content", Static).update,
                f"[red]Request failed: {e}[/red]",
            )
            self.app.call_from_thread(self._re_enable)

    def _show_results(self, data: dict) -> None:
        results = data.get("results", [])
        succeeded = data.get("succeeded", 0)
        failed = data.get("failed", 0)

        lines = []
        for r in results:
            pos = r.get("position", "?")
            ip = r.get("ip") or "—"
            if r.get("success"):
                lines.append(f"[green]✓[/green] {pos} ({ip})")
                if r.get("error"):
                    lines.append(f"  [yellow]{r['error']}[/yellow]")
            else:
                lines.append(f"[red]✗[/red] {pos} ({ip}): {r.get('error', 'failed')}")

        summary = f"\n[bold]{succeeded} succeeded, {failed} failed[/bold]"
        self.query_one("#results-content", Static).update("\n".join(lines) + summary)
        self._re_enable()

    def _re_enable(self) -> None:
        self.query_one("#deploy", Button).disabled = False
        self.query_one("#pwd-input", Input).disabled = False
