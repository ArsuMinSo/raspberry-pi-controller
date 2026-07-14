from concurrent.futures import ThreadPoolExecutor, as_completed

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.utils.formatters import fmt_datetime, fmt_tags, fmt_uptime, status_markup
from frontend.screens.confirm import ConfirmScreen
from frontend.screens.deploy_key import DeployKeyScreen
from frontend.screens.manage_pi import ManagePiScreen
from frontend.screens.settings import SettingsScreen


_COLUMNS = [
    ("",          2),
    ("Position", 10),
    ("Hostname", 24),
    ("IP",       16),
    ("MAC",      19),
    ("Status",   14),
    ("Ver",       5),
    ("CPU 1m%",   9),
    ("CPU 5m%",   9),
    ("CPU 15m%", 10),
    ("RAM%",      7),
    ("Temp °C",   9),
    ("Pi Time",  16),
    ("Uptime",   10),
    ("Tags",     24),
    ("Last Seen", 22),
]

_SORT_KEYS = [
    None,
    lambda p: (p.get("position") or "").lower(),
    lambda p: (p.get("hostname") or "").lower(),
    lambda p: _ip_sort_key(p.get("ip")),
    lambda p: (p.get("mac") or "").lower(),
    lambda p: p.get("status") or "",
    lambda p: p.get("pi_version") or 0,
    lambda p: p.get("cpu_1m") or 0.0,
    lambda p: p.get("cpu_5m") or 0.0,
    lambda p: p.get("cpu_15m") or 0.0,
    lambda p: p.get("mem_percent") or 0.0,
    lambda p: p.get("temp_c") or 0.0,
    lambda p: p.get("pi_time") or "",
    lambda p: p.get("uptime_s") or 0,
    lambda p: ",".join(sorted(p.get("tags") or [])),
    lambda p: str(p.get("last_seen") or ""),
]


def _ip_sort_key(ip: str | None) -> tuple:
    if not ip:
        return (999, 999, 999, 999)
    try:
        return tuple(int(part) for part in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)


class HomeScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_select", "Select", show=True),
        Binding("a", "select_all", "All"),
        Binding("A", "deselect_all", "None"),
        Binding("n", "add_pi", "Add"),
        Binding("e", "edit_pi", "Edit"),
        Binding("d", "delete_pi", "Delete"),
        Binding("x", "execute", "Execute"),
        Binding("h", "health", "Health"),
        Binding("l", "logs", "Logs"),
        Binding("D", "discovery", "Discover"),
        Binding("k", "deploy_key", "Deploy Key"),
        Binding("s", "settings", "Settings"),
    ]

    DEFAULT_CSS = """
    HomeScreen {
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
    #health-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api
        self._pis: list[dict] = []
        self._health: dict[str, dict] = {}
        self.selected: set[str] = set()
        self._sort_col: int | None = None
        self._sort_asc: bool = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading Pi inventory…", id="subtitle")
        yield DataTable(id="pi-table", cursor_type="row", zebra_stripes=True)
        yield Label("", id="health-status")
        yield Footer()

    def on_mount(self) -> None:
        self._redraw_table()
        self.load_pis()

    @work(thread=True)
    def load_pis(self) -> None:
        try:
            pis = self._api.list_pis()
        except ApiError as e:
            self.app.call_from_thread(self._on_load_error, str(e))
            return
        self.app.call_from_thread(self._on_pis_loaded, pis)

    def _on_pis_loaded(self, pis: list[dict]) -> None:
        self._pis = pis
        self._merge_health()
        self._apply_sort()
        reachable = sum(1 for p in pis if p.get("status") == "reachable")
        self.query_one("#subtitle", Label).update(
            f"{len(pis)} Pi(s) — {reachable} reachable, {len(self.selected)} selected"
        )

    def _on_load_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

    def _merge_health(self) -> None:
        for pi in self._pis:
            pos = pi.get("position")
            if pos and pos in self._health:
                h = self._health[pos]
                pi["cpu_1m"]      = h.get("cpu_1m")
                pi["cpu_5m"]      = h.get("cpu_5m")
                pi["cpu_15m"]     = h.get("cpu_15m")
                pi["mem_percent"] = h.get("mem_percent")
                pi["temp_c"]      = h.get("temp_c")
                pi["pi_time"]     = h.get("pi_time")
                pi["uptime_s"]    = h.get("uptime_s")
                pi["status"]      = "unreachable" if h.get("error") else "reachable"

    def _apply_sort(self) -> None:
        if self._sort_col is not None and _SORT_KEYS[self._sort_col] is not None:
            self._pis.sort(key=_SORT_KEYS[self._sort_col], reverse=not self._sort_asc)
        self._redraw_table()

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for i, (label, width) in enumerate(_COLUMNS):
            if self._sort_col == i:
                label += " ▲" if self._sort_asc else " ▼"
            table.add_column(label, width=width)
        for pi in self._pis:
            pos     = pi.get("position", "")
            cpu_1m  = pi.get("cpu_1m")
            cpu_5m  = pi.get("cpu_5m")
            cpu_15m = pi.get("cpu_15m")
            mem_pct = pi.get("mem_percent")
            temp    = pi.get("temp_c")
            table.add_row(
                "✓" if pos in self.selected else " ",
                pos,
                pi.get("hostname") or "—",
                pi.get("ip") or "—",
                pi.get("mac") or "—",
                status_markup(pi.get("status", "unreachable")),
                str(pi.get("pi_version") or "—"),
                f"{cpu_1m:.1f}"  if cpu_1m  is not None else "—",
                f"{cpu_5m:.1f}"  if cpu_5m  is not None else "—",
                f"{cpu_15m:.1f}" if cpu_15m is not None else "—",
                f"{mem_pct:.1f}" if mem_pct is not None else "—",
                f"{temp:.1f}"    if temp    is not None else "—",
                fmt_datetime(pi.get("pi_time")),
                fmt_uptime(pi.get("uptime_s")),
                fmt_tags(pi.get("tags", [])),
                fmt_datetime(pi.get("last_seen")),
                key=pos,
            )

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        col = event.column_index
        if col == 0 or _SORT_KEYS[col] is None:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_sort()

    def _refresh_subtitle(self) -> None:
        reachable = sum(1 for p in self._pis if p.get("status") == "reachable")
        self.query_one("#subtitle", Label).update(
            f"{len(self._pis)} Pi(s) — {reachable} reachable, [bold]{len(self.selected)} selected[/bold]"
        )

    def _current_position(self) -> str | None:
        table = self.query_one(DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._pis):
            return None
        return self._pis[table.cursor_row].get("position")

    def _redraw_sel_column(self) -> None:
        table = self.query_one(DataTable)
        for i, pi in enumerate(self._pis):
            pos = pi.get("position", "")
            mark = "✓" if pos in self.selected else " "
            table.update_cell_at((i, 0), mark)

    def action_toggle_select(self) -> None:
        pos = self._current_position()
        if pos is None:
            return
        if pos in self.selected:
            self.selected.discard(pos)
        else:
            self.selected.add(pos)
        self._redraw_sel_column()
        self._refresh_subtitle()

    def action_select_all(self) -> None:
        self.selected = {p["position"] for p in self._pis if p.get("position")}
        self._redraw_sel_column()
        self._refresh_subtitle()

    def action_deselect_all(self) -> None:
        self.selected.clear()
        self._redraw_sel_column()
        self._refresh_subtitle()

    def action_refresh(self) -> None:
        self.query_one("#subtitle", Label).update("Refreshing…")
        self.load_pis()

    def action_execute(self) -> None:
        if not self.selected:
            self.notify("Select at least one Pi first (Space)", severity="warning")
            return
        self.app.push_screen("execute")

    def action_health(self) -> None:
        if self.selected:
            positions = sorted(self.selected)
        else:
            positions = [p["position"] for p in self._pis if p.get("status") == "reachable"]
        if not positions:
            self.notify("No reachable Pis to check", severity="warning")
            return
        self._set_health_status(f"[yellow]Starting health check for {len(positions)} Pi(s)…[/yellow]")
        self._run_health(positions)

    @work(thread=True)
    def _run_health(self, positions: list[str]) -> None:
        total = len(positions)
        ok_count = 0
        done = 0

        def _check_one(pos: str) -> tuple[str, dict | None]:
            try:
                resp = self._api.trigger_health(positions=[pos])
                return pos, self._api.get_health_result(resp["action_id"])
            except ApiError:
                return pos, None

        with ThreadPoolExecutor(max_workers=min(10, total)) as ex:
            futures = {ex.submit(_check_one, pos): pos for pos in positions}
            for future in as_completed(futures):
                pos, result = future.result()
                done += 1
                if result:
                    for r in result.get("results", []):
                        p = r.get("position")
                        if p:
                            self._health[p] = r
                    if result.get("status") == "success":
                        ok_count += 1
                self.app.call_from_thread(self._update_health_bar, done, total, pos)
                self.app.call_from_thread(self._merge_and_redraw)

        self.app.call_from_thread(self._on_health_done, ok_count, total)

    def _update_health_bar(self, done: int, total: int, last: str) -> None:
        pct = done / total if total > 0 else 0
        filled = int(30 * pct)
        bar = "█" * filled + "░" * (30 - filled)
        self._set_health_status(
            f"[yellow][{bar}] {done}/{total}  ✓ {last}[/yellow]"
        )

    def _merge_and_redraw(self) -> None:
        self._merge_health()
        self._apply_sort()

    def _on_health_done(self, ok: int, total: int) -> None:
        color = "green" if ok == total else ("red" if ok == 0 else "yellow")
        self._set_health_status(
            f"[{color}][{'█' * 30}] {ok}/{total} OK[/{color}]"
            "  [dim]CPU: load avg % (1/5/15 min)[/dim]"
        )

    def _set_health_status(self, msg: str) -> None:
        self.query_one("#health-status", Label).update(msg)

    def action_logs(self) -> None:
        self.app.push_screen("logs")

    def action_add_pi(self) -> None:
        def _on_result(data: dict | None) -> None:
            if data is None:
                return
            self._do_create_pi(data)

        self.app.push_screen(ManagePiScreen(), _on_result)

    def action_edit_pi(self) -> None:
        pi = self._current_pi()
        if pi is None:
            self.notify("No Pi selected", severity="warning")
            return

        def _on_result(data: dict | None) -> None:
            if data is None:
                return
            self._do_update_pi(pi["position"], data)

        self.app.push_screen(ManagePiScreen(pi=pi), _on_result)

    def action_delete_pi(self) -> None:
        targets = list(self.selected) if self.selected else []
        if not targets:
            pos = self._current_position()
            if pos:
                targets = [pos]
        if not targets:
            self.notify("Nothing to delete", severity="warning")
            return
        if len(targets) == 1:
            msg = f"Delete [bold]{targets[0]}[/bold]?"
        else:
            msg = f"Delete [bold]{len(targets)} Pis[/bold]?\n{', '.join(sorted(targets)[:10])}" + (
                f"\n… and {len(targets) - 10} more" if len(targets) > 10 else ""
            )

        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete_pis(targets)

        self.app.push_screen(
            ConfirmScreen(msg, title="Delete Pi(s)", confirm_label="Delete  [Enter]"),
            _on_confirm,
        )

    def _current_pi(self) -> dict | None:
        table = self.query_one(DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._pis):
            return None
        return self._pis[table.cursor_row]

    @work(thread=True)
    def _do_create_pi(self, data: dict) -> None:
        try:
            self._api.create_pi(**data)
            self.app.call_from_thread(self.notify, f"Added {data['position']}")
            self.app.call_from_thread(self.load_pis)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_update_pi(self, position: str, data: dict) -> None:
        fields = {k: v for k, v in data.items() if k != "position"}
        try:
            self._api.update_pi(position, **fields)
            self.app.call_from_thread(self.notify, f"Updated {position}")
            self.app.call_from_thread(self.load_pis)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    def action_discovery(self) -> None:
        self.app.push_screen("discovery")

    def action_deploy_key(self) -> None:
        targets = sorted(self.selected) if self.selected else []
        if not targets:
            pos = self._current_position()
            if pos:
                targets = [pos]
        if not targets:
            self.notify("Select at least one Pi first (Space)", severity="warning")
            return
        self.app.push_screen(DeployKeyScreen(self._api, targets))

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen(self._api))

    @work(thread=True)
    def _do_delete_pis(self, positions: list[str]) -> None:
        errors = []
        for pos in positions:
            try:
                self._api.delete_pi(pos)
            except ApiError as e:
                errors.append(f"{pos}: {e}")
        if errors:
            self.app.call_from_thread(self.notify, "\n".join(errors), severity="error")
        else:
            self.app.call_from_thread(self.notify, f"Deleted {len(positions)} Pi(s)")
        self.app.call_from_thread(self.selected.difference_update, positions)
        self.app.call_from_thread(self.load_pis)
