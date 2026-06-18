from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError


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
        table = self.query_one(DataTable)
        table.add_columns("Position", "CPU %", "Mem Used", "Mem Total", "Disk Used", "Disk Total", "Error")
        if self._selected:
            self._run_check()

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
        results = result.get("results", [])
        table = self.query_one(DataTable)
        table.clear()
        for r in results:
            cpu = r.get("cpu_percent")
            mem_used = r.get("mem_used_mb")
            mem_total = r.get("mem_total_mb")
            disk_used = r.get("disk_used_gb")
            disk_total = r.get("disk_total_gb")

            cpu_str = f"{cpu:.1f}" if cpu is not None else "—"
            mem_used_str = f"{mem_used}MB" if mem_used is not None else "—"
            mem_total_str = f"{mem_total}MB" if mem_total is not None else "—"
            disk_used_str = f"{disk_used:.1f}GB" if disk_used is not None else "—"
            disk_total_str = f"{disk_total:.1f}GB" if disk_total is not None else "—"
            error = r.get("error") or ""

            table.add_row(
                r.get("position", ""),
                cpu_str,
                mem_used_str,
                mem_total_str,
                disk_used_str,
                disk_total_str,
                error,
                key=r.get("position"),
            )

        status = result.get("status", "")
        color = "green" if status == "success" else ("red" if status == "fail" else "yellow")
        self.query_one("#subtitle", Label).update(
            f"[{color}]{status.upper()}[/{color}] — {len(results)} Pi(s) checked"
        )

    def _on_error(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(f"[red]Error: {msg}[/red]")

    def action_trigger_all(self) -> None:
        self._run_check(all_pis=True)

    def action_back(self) -> None:
        self.app.pop_screen()
