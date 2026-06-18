from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static
from textual.containers import Horizontal, Vertical
from textual.binding import Binding


class ManagePiScreen(ModalScreen):
    """Add or edit a Pi. Pass existing pi dict to edit, None to add."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ManagePiScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    Input {
        margin-bottom: 0;
    }
    #error {
        color: $error;
        height: 1;
        margin-top: 1;
    }
    #buttons {
        margin-top: 2;
        height: 3;
        align: right middle;
    }
    Button {
        margin-left: 1;
    }
    """

    def __init__(self, pi: dict | None = None):
        super().__init__()
        self._pi = pi
        self._editing = pi is not None

    def compose(self) -> ComposeResult:
        pi = self._pi or {}
        title = f"Edit Pi — {pi.get('position', '')}" if self._editing else "Add Pi"
        with Vertical(id="dialog"):
            yield Label(title, id="title")

            yield Label("Position (XX-XXX) *", classes="field-label")
            yield Input(
                value=pi.get("position", ""),
                placeholder="01-001",
                id="input-position",
                disabled=self._editing,
            )

            yield Label("MAC address *", classes="field-label")
            yield Input(
                value=pi.get("mac", ""),
                placeholder="aa:bb:cc:dd:ee:ff",
                id="input-mac",
            )

            yield Label("Hostname", classes="field-label")
            yield Input(
                value=pi.get("hostname") or "",
                placeholder="kiosk-01",
                id="input-hostname",
            )

            yield Label("IP address", classes="field-label")
            yield Input(
                value=pi.get("ip") or "",
                placeholder="10.10.20.5",
                id="input-ip",
            )

            yield Label("Pi version (2-5)", classes="field-label")
            yield Input(
                value=str(pi.get("pi_version") or ""),
                placeholder="4",
                id="input-version",
            )

            yield Label("Tags (comma-separated)", classes="field-label")
            yield Input(
                value=", ".join(pi.get("tags") or []),
                placeholder="kiosk, floor1",
                id="input-tags",
            )

            yield Label("", id="error")

            with Horizontal(id="buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button(
                    "Save" if self._editing else "Add",
                    variant="primary",
                    id="btn-save",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        position = self.query_one("#input-position", Input).value.strip()
        mac = self.query_one("#input-mac", Input).value.strip()
        hostname = self.query_one("#input-hostname", Input).value.strip() or None
        ip = self.query_one("#input-ip", Input).value.strip() or None
        version_str = self.query_one("#input-version", Input).value.strip()
        tags_raw = self.query_one("#input-tags", Input).value.strip()

        import re
        error = self.query_one("#error", Label)

        if not self._editing and not re.match(r"^\d{2}-\d{3}$", position):
            error.update("Position must be XX-XXX (e.g. 01-001)")
            return
        if not re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", mac):
            error.update("Invalid MAC address")
            return

        pi_version = None
        if version_str:
            try:
                pi_version = int(version_str)
                if pi_version not in (2, 3, 4, 5):
                    raise ValueError
            except ValueError:
                error.update("Version must be 2, 3, 4, or 5")
                return

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        self.dismiss({
            "position": position,
            "mac": mac,
            "hostname": hostname,
            "ip": ip,
            "pi_version": pi_version,
            "tags": tags,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)
