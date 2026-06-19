from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.utils.formatters import fmt_datetime, fmt_tags, status_markup
from frontend.screens.confirm import ConfirmScreen
from frontend.screens.deploy_key import DeployKeyScreen
from frontend.screens.manage_pi import ManagePiScreen
from frontend.screens.settings import SettingsScreen


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
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api
        self._pis: list[dict] = []
        self.selected: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading Pi inventory…", id="subtitle")
        yield DataTable(id="pi-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Position", "Hostname", "IP", "MAC", "Status", "Ver", "Tags", "Last Seen")
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
        table = self.query_one(DataTable)
        table.clear()
        for pi in pis:
            pos = pi.get("position", "")
            sel = "✓" if pos in self.selected else " "
            table.add_row(
                sel,
                pos,
                pi.get("hostname") or "—",
                pi.get("ip") or "—",
                pi.get("mac") or "—",
                status_markup(pi.get("status", "unreachable")),
                str(pi.get("pi_version") or "—"),
                fmt_tags(pi.get("tags", [])),
                fmt_datetime(pi.get("last_seen")),
                key=pos,
            )
        reachable = sum(1 for p in pis if p.get("status") == "reachable")
        self.query_one("#subtitle", Label).update(
            f"{len(pis)} Pi(s) — {reachable} reachable, {len(self.selected)} selected"
        )

    def _on_load_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

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
        self.app.push_screen("health")

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

        self.app.push_screen(ConfirmScreen(msg, title="Delete Pi(s)"), _on_confirm)

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
        def _on_result(path: str | None) -> None:
            if path:
                self.notify(f"SSH key path updated")

        self.app.push_screen(SettingsScreen(self._api), _on_result)

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
