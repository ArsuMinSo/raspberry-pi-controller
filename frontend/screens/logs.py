from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.utils.formatters import fmt_datetime, truncate


class LogsScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    LogsScreen {
        layout: vertical;
    }
    #subtitle {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading logs…", id="subtitle")
        yield DataTable(id="logs-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Action", "Pis", "Status", "Duration", "Command")
        self.load_logs()

    @work(thread=True)
    def load_logs(self) -> None:
        try:
            entries = self._api.get_logs(limit=200)
        except ApiError as e:
            self.app.call_from_thread(self._on_error, str(e))
            return
        self.app.call_from_thread(self._on_loaded, entries)

    def _on_loaded(self, entries: list[dict]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for e in entries:
            status = e.get("status", "")
            color = "green" if status == "success" else ("red" if status == "fail" else "yellow")
            pis = ", ".join(e.get("pis_selected", []))
            table.add_row(
                fmt_datetime(e.get("timestamp")),
                e.get("action", ""),
                truncate(pis, 30),
                f"[{color}]{status}[/{color}]",
                str(e.get("duration_ms") or "—"),
                truncate(e.get("command"), 40),
            )
        self.query_one("#subtitle", Label).update(f"{len(entries)} log entries")

    def _on_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

    def action_refresh(self) -> None:
        self.query_one("#subtitle", Label).update("Refreshing…")
        self.load_logs()

    def action_back(self) -> None:
        self.app.pop_screen()
