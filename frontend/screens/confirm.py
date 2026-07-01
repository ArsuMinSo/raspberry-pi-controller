from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "dismiss_false", "Cancel", show=False),
        Binding("enter", "dismiss_true", "Confirm", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 60;
        height: auto;
        border: thick $error;
        padding: 1 2;
        background: $surface;
        layout: vertical;
    }
    #confirm-title {
        text-align: center;
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    #confirm-msg {
        text-align: center;
        height: auto;
        margin-bottom: 1;
    }
    #btn-row {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #btn-cancel {
        margin-right: 2;
    }
    """

    def __init__(self, message: str, title: str = "Confirm", confirm_label: str = "Confirm  [Enter]"):
        super().__init__()
        self._message = message
        self._title = title
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Static(id="confirm-dialog"):
            yield Label(self._title, id="confirm-title")
            yield Label(self._message, id="confirm-msg")
            with Horizontal(id="btn-row"):
                yield Button("Cancel  [Esc]", variant="default", id="btn-cancel")
                yield Button(self._confirm_label, variant="error", id="btn-confirm")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)

    def action_dismiss_true(self) -> None:
        self.dismiss(True)
