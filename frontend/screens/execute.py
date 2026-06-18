from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.detail import DetailScreen
from frontend.utils.formatters import truncate


class ExecuteScreen(Screen):
    BINDINGS = [
        Binding("v", "detail", "View detail"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    ExecuteScreen {
        layout: vertical;
    }
    #selected-pis {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }
    #cmd-label {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    Input {
        margin: 0 1;
    }
    #results-label {
        height: 1;
        padding: 0 1;
        margin-top: 1;
        color: $text-muted;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, api: ApiClient, selected: set[str]):
        super().__init__()
        self._api = api
        self._selected = sorted(selected)
        self._results: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            f"Selected ({len(self._selected)}): {', '.join(self._selected)}",
            id="selected-pis",
        )
        yield Label("Command:", id="cmd-label")
        yield Input(placeholder="e.g. uptime", id="cmd-input")
        yield Label("Results: (v or Enter on row for full output)", id="results-label")
        yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Position", "Exit", "Stdout", "Stderr", "Error")
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if not command:
            return
        self._run_command(command)

    @work(thread=True)
    def _run_command(self, command: str) -> None:
        self.app.call_from_thread(self._set_running, command)
        try:
            resp = self._api.execute_command(self._selected, command)
            action_id = resp["action_id"]
            result = self._api.get_command_result(action_id)
            self.app.call_from_thread(self._on_results, result)
        except ApiError as e:
            self.app.call_from_thread(self._on_error, str(e))

    def _set_running(self, command: str) -> None:
        self.query_one("#results-label", Label).update(
            f"[yellow]Executing:[/yellow] {command}"
        )
        self.query_one(DataTable).clear()
        self.query_one(Input).disabled = True

    def _on_results(self, result: dict) -> None:
        self._results = result.get("results", [])
        table = self.query_one(DataTable)
        table.clear()
        success = 0
        for r in self._results:
            ec = r.get("exit_code")
            ec_str = str(ec) if ec is not None else "—"
            if ec == 0:
                success += 1
            table.add_row(
                r.get("position", ""),
                ec_str,
                truncate(r.get("stdout"), 60),
                truncate(r.get("stderr"), 40),
                r.get("error") or "",
                key=r.get("position"),
            )
        total = len(self._results)
        status = result.get("status", "")
        color = "green" if status == "success" else ("red" if status == "fail" else "yellow")
        self.query_one("#results-label", Label).update(
            f"[{color}]{status.upper()}[/{color}] — {success}/{total} succeeded  "
            f"(Enter on row for full output)"
        )
        self.query_one(Input).disabled = False
        self.query_one(Input).clear()
        self.query_one(Input).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_detail()

    def _on_error(self, msg: str) -> None:
        self.query_one("#results-label", Label).update(f"[red]Error: {msg}[/red]")
        self.query_one(Input).disabled = False
        self.query_one(Input).focus()

    def action_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        pos = r.get("position", "?")
        ec = r.get("exit_code")
        meta = [
            ("Position", pos),
            ("Exit code", str(ec) if ec is not None else "—"),
            ("Error", r.get("error") or "—"),
        ]
        stdout = r.get("stdout") or ""
        stderr = r.get("stderr") or ""
        body = ""
        if stdout:
            body += "─── STDOUT ─────────────────────────────────────────\n"
            body += stdout.rstrip() + "\n"
        if stderr:
            body += "\n─── STDERR ─────────────────────────────────────────\n"
            body += stderr.rstrip() + "\n"
        if not body:
            body = "(no output)"
        self.app.push_screen(DetailScreen(f"Result: {pos}", meta, body))

    def action_back(self) -> None:
        self.app.pop_screen()
