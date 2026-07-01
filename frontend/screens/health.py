from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError


_COLUMNS = [
    ("Position",  12),
    ("CPU 1m%",    9),
    ("CPU 5m%",    9),
    ("CPU 15m%",  10),
    ("RAM%",       7),
    ("Temp °C",    9),
    ("Error",     30),
]

_SORT_KEYS = [
    lambda r: (r.get("position") or "").lower(),
    lambda r: r.get("cpu_1m")      or 0.0,
    lambda r: r.get("cpu_5m")      or 0.0,
    lambda r: r.get("cpu_15m")     or 0.0,
    lambda r: r.get("mem_percent") or 0.0,
    lambda r: r.get("temp_c")      or 0.0,
    lambda r: (r.get("error") or "").lower(),
]


class HealthScreen(Screen):
    BINDINGS = [
        Binding("t", "trigger_all", "Check All"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    HealthScreen {
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

    def __init__(self, api: ApiClient, selected: set[str] | None = None):
        super().__init__()
        self._api = api
        self._selected = selected or set()
        self._results: list[dict] = []
        self._sort_col: int | None = None
        self._sort_asc: bool = True

    def compose(self) -> ComposeResult:
        yield Header()
        hint = (
            f"Checking {len(self._selected)} selected Pi(s)"
            if self._selected
            else "Press t to check all reachable Pis"
        )
        yield Label(hint, id="subtitle")
        yield DataTable(id="health-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._redraw_table()
        if self._selected:
            self._run_check()

    def _apply_sort(self) -> None:
        if self._sort_col is not None:
            self._results.sort(key=_SORT_KEYS[self._sort_col], reverse=not self._sort_asc)
        self._redraw_table()

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for i, (label, width) in enumerate(_COLUMNS):
            if self._sort_col == i:
                label += " ▲" if self._sort_asc else " ▼"
            table.add_column(label, width=width)
        for r in self._results:
            cpu_1m  = r.get("cpu_1m")
            cpu_5m  = r.get("cpu_5m")
            cpu_15m = r.get("cpu_15m")
            mem_pct = r.get("mem_percent")
            temp    = r.get("temp_c")
            table.add_row(
                r.get("position", ""),
                f"{cpu_1m:.1f}"  if cpu_1m  is not None else "—",
                f"{cpu_5m:.1f}"  if cpu_5m  is not None else "—",
                f"{cpu_15m:.1f}" if cpu_15m is not None else "—",
                f"{mem_pct:.1f}" if mem_pct is not None else "—",
                f"{temp:.1f}"    if temp    is not None else "—",
                r.get("error") or "",
                key=r.get("position"),
            )

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        col = event.column_index
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_sort()

    @work(thread=True)
    def _run_check(self, all_pis: bool = False) -> None:
        self.app.call_from_thread(
            self.query_one("#subtitle", Label).update,
            "[yellow]Running health check…[/yellow]",
        )
        try:
            if all_pis or not self._selected:
                resp = self._api.trigger_health(all_pis=True)
            else:
                resp = self._api.trigger_health(positions=list(self._selected))
            action_id = resp["action_id"]
            result = self._api.get_health_result(action_id)
            self.app.call_from_thread(self._on_results, result)
        except ApiError as e:
            self.app.call_from_thread(self._on_error, str(e))

    def _on_results(self, result: dict) -> None:
        self._results = result.get("results", [])
        self._apply_sort()
        status = result.get("status", "")
        color = "green" if status == "success" else ("red" if status == "fail" else "yellow")
        self.query_one("#subtitle", Label).update(
            f"[{color}]{status.upper()}[/{color}] — {len(self._results)} Pi(s) checked"
            "  [dim]CPU: load avg % (1/5/15 min)[/dim]"
        )

    def _on_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

    def action_trigger_all(self) -> None:
        self._run_check(all_pis=True)

    def action_back(self) -> None:
        self.app.pop_screen()
