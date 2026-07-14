import json

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.detail import DetailScreen
from frontend.utils.formatters import fmt_datetime, fmt_duration, truncate


_COLUMNS = [
    ("Time",     14),
    ("Action",   12),
    ("Pis",      28),
    ("Status",   12),
    ("Duration", 10),
    ("Command",  36),
]

_SORT_KEYS = [
    lambda e: e.get("timestamp") or "",
    lambda e: (e.get("action") or "").lower(),
    lambda e: ", ".join(e.get("pis_selected") or []),
    lambda e: e.get("status") or "",
    lambda e: e.get("duration_ms") or 0,
    lambda e: (e.get("command") or "").lower(),
]


_LIMIT_STEP = 300
_LIMIT_MAX = 1000


class LogsScreen(Screen):
    BINDINGS = [
        Binding("v", "detail", "View detail"),
        Binding("r", "refresh", "Refresh"),
        Binding("f", "toggle_filter", "Toggle filter"),
        Binding("m", "load_more", "Load more"),
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

    def __init__(self, api: ApiClient, selected: set[str] | None = None):
        super().__init__()
        self._api = api
        self._selected = selected or set()
        self._filter_active = bool(self._selected)
        self._limit = _LIMIT_STEP
        self._all_entries: list[dict] = []
        self._entries: list[dict] = []
        self._sort_col: int | None = None
        self._sort_asc: bool = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading logs…", id="subtitle")
        yield DataTable(id="logs-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._redraw_table()
        self.load_logs()

    def _apply_filter(self) -> None:
        if self._filter_active and self._selected:
            self._entries = [
                e for e in self._all_entries
                if set(e.get("pis_selected") or []) & self._selected
            ]
        else:
            self._entries = list(self._all_entries)
        self._apply_sort()

    def _apply_sort(self) -> None:
        if self._sort_col is not None:
            self._entries.sort(key=_SORT_KEYS[self._sort_col], reverse=not self._sort_asc)
        self._redraw_table()

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for i, (label, width) in enumerate(_COLUMNS):
            if self._sort_col == i:
                label += " ▲" if self._sort_asc else " ▼"
            table.add_column(label, width=width)
        for e in self._entries:
            status = e.get("status", "")
            color = "green" if status == "success" else ("red" if status == "fail" else "yellow")
            pis = ", ".join(e.get("pis_selected", []))
            table.add_row(
                fmt_datetime(e.get("timestamp")),
                e.get("action", ""),
                truncate(pis, 30),
                f"[{color}]{status}[/{color}]",
                fmt_duration(e.get("duration_ms")),
                truncate(e.get("command"), 40),
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
    def load_logs(self) -> None:
        try:
            entries = self._api.get_logs(limit=self._limit)
        except ApiError as e:
            self.app.call_from_thread(self._on_error, str(e))
            return
        self.app.call_from_thread(self._on_loaded, entries)

    def _on_loaded(self, entries: list[dict]) -> None:
        self._all_entries = entries
        self._apply_filter()
        filter_note = ""
        if self._selected:
            state = "on" if self._filter_active else "off"
            filter_note = f"  [dim]filter {state} ({len(self._selected)} pi) — f to toggle[/dim]"
        more_note = "" if self._limit >= _LIMIT_MAX else "  [dim]m for more[/dim]"
        self.query_one("#subtitle", Label).update(
            f"{len(self._entries)}/{len(self._all_entries)} log entries "
            f"(fetched {len(entries)}, limit {self._limit}){filter_note}{more_note}"
        )

    def _on_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

    def action_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._entries):
            return
        e = self._entries[row]
        pis = ", ".join(e.get("pis_selected", []))
        meta = [
            ("Time", fmt_datetime(e.get("timestamp"))),
            ("Action", e.get("action", "—")),
            ("Pis", pis or "—"),
            ("Command", e.get("command") or "—"),
            ("Status", e.get("status", "—")),
            ("Duration", fmt_duration(e.get("duration_ms"))),
            ("Exit code", str(e.get("exit_code")) if e.get("exit_code") is not None else "—"),
        ]
        body = _format_log_body(e)
        self.app.push_screen(DetailScreen(f"Log #{e.get('id', '?')}", meta, body))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_detail()

    def action_refresh(self) -> None:
        self.query_one("#subtitle", Label).update("Refreshing…")
        self.load_logs()

    def action_toggle_filter(self) -> None:
        if not self._selected:
            return
        self._filter_active = not self._filter_active
        self._apply_filter()
        state = "on" if self._filter_active else "off"
        filter_note = f"  [dim]filter {state} ({len(self._selected)} pi) — f to toggle[/dim]"
        more_note = "" if self._limit >= _LIMIT_MAX else "  [dim]m for more[/dim]"
        self.query_one("#subtitle", Label).update(
            f"{len(self._entries)}/{len(self._all_entries)} log entries "
            f"(limit {self._limit}){filter_note}{more_note}"
        )

    def action_load_more(self) -> None:
        if self._limit >= _LIMIT_MAX:
            return
        self._limit = min(self._limit + _LIMIT_STEP, _LIMIT_MAX)
        self.query_one("#subtitle", Label).update("Loading more…")
        self.load_logs()

    def action_back(self) -> None:
        self.app.pop_screen()


def _format_log_body(e: dict) -> str:
    raw_stdout = e.get("stdout") or ""
    raw_stderr = e.get("stderr") or ""

    if raw_stdout.startswith("["):
        try:
            results = json.loads(raw_stdout)
            lines = []
            for r in results:
                pos = r.get("position", "?")
                ec = r.get("exit_code")
                err = r.get("error")
                lines.append(f"── {pos}  exit={ec if ec is not None else '—'}  {('ERR: ' + err) if err else ''}")
                if r.get("stdout"):
                    lines.append(r["stdout"].rstrip())
                if r.get("stderr"):
                    lines.append("[stderr] " + r["stderr"].rstrip())
                lines.append("")
            return "\n".join(lines).rstrip() or "(no per-Pi output)"
        except (json.JSONDecodeError, TypeError):
            pass

    body = ""
    if raw_stdout:
        body += "─── STDOUT ─────────────────────────────────────────\n"
        body += raw_stdout.rstrip() + "\n"
    if raw_stderr:
        body += "\n─── STDERR ─────────────────────────────────────────\n"
        body += raw_stderr.rstrip() + "\n"
    return body or "(no output)"
