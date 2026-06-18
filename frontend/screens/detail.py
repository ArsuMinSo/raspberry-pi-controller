from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class DetailScreen(ModalScreen):
    """Generic scrollable detail view for command results or log entries."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    DetailScreen {
        align: center middle;
    }
    #detail-dialog {
        width: 92%;
        height: 88%;
        border: thick $primary;
        padding: 1 2;
        background: $surface;
        layout: vertical;
    }
    #detail-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .meta {
        height: auto;
        color: $text-muted;
    }
    #detail-body {
        height: 1fr;
        border: solid $panel;
        background: $panel-darken-1;
        padding: 0 1;
        margin-top: 1;
    }
    #detail-content {
        height: auto;
    }
    #close-row {
        height: auto;
        layout: horizontal;
        align: right middle;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, meta: list[tuple[str, str]], body: str):
        super().__init__()
        self._title = title
        self._meta = meta
        self._body = body

    def compose(self) -> ComposeResult:
        with Static(id="detail-dialog"):
            yield Label(self._title, id="detail-title")
            for label, value in self._meta:
                yield Label(f"[bold]{label}:[/bold] {value}", classes="meta")
            with ScrollableContainer(id="detail-body"):
                yield Static(self._body or "(no output)", id="detail-content")
            with Static(id="close-row"):
                yield Button("Close  [Esc]", variant="default", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
