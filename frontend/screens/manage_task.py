from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static


class ManageTaskScreen(ModalScreen[dict | None]):
    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    DEFAULT_CSS = """
    ManageTaskScreen {
        align: center middle;
    }
    #dialog {
        width: 70;
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
    .field-label {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    .field-hint {
        height: 1;
        color: $text-muted;
        text-style: dim;
    }
    #buttons {
        layout: horizontal;
        height: auto;
        align: right middle;
        margin-top: 2;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, task: dict | None = None):
        super().__init__()
        self._task = task or {}
        self._editing = bool(task)

    def compose(self) -> ComposeResult:
        t = self._task
        with Static(id="dialog"):
            yield Label("Edit Task" if self._editing else "New Scheduled Task", id="title")

            yield Label("Name:", classes="field-label")
            yield Input(value=t.get("name", ""), placeholder="e.g. Daily health check", id="name")

            yield Label("Type:", classes="field-label")
            yield Select(
                [("Command (SSH)", "command"), ("Health check", "health"), ("Discovery scan", "discovery")],
                value=t.get("task_type", "command"),
                id="type-select",
                allow_blank=False,
            )

            yield Label("Command: (only for Command type)", classes="field-label")
            yield Input(value=t.get("command", "") or "", placeholder="e.g. systemctl restart kiosk", id="command")

            yield Label("Cron expression:", classes="field-label")
            yield Input(value=t.get("cron", ""), placeholder="* * * * *  (min hr dom mon dow)", id="cron")
            yield Label("  Examples: '*/5 * * * *'=every 5min  '0 3 * * *'=3am daily  '0 0 * * 0'=weekly", classes="field-hint")

            yield Label("Target Pi positions (comma-separated, blank=all reachable):", classes="field-label")
            yield Input(value=", ".join(t.get("pis", [])), placeholder="01-001, 01-002 … or blank for all", id="pis")

            with Horizontal(id="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self._submit()

    def action_dismiss_none(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        cron = self.query_one("#cron", Input).value.strip()
        task_type = str(self.query_one("#type-select", Select).value)
        command = self.query_one("#command", Input).value.strip() or None
        pis_raw = self.query_one("#pis", Input).value.strip()
        pis = [p.strip() for p in pis_raw.split(",") if p.strip()] if pis_raw else []

        if not name:
            self.notify("Name is required", severity="warning")
            return
        if not cron:
            self.notify("Cron expression is required", severity="warning")
            return
        if task_type == "command" and not command:
            self.notify("Command is required for Command type", severity="warning")
            return

        self.dismiss({
            "name": name,
            "cron": cron,
            "task_type": task_type,
            "command": command,
            "pis": pis,
        })
