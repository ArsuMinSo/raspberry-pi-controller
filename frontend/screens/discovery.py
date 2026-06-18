from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual import work

from frontend.api_client import ApiClient, ApiError


class DiscoveryScreen(Screen):
    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    DiscoveryScreen {
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
        yield Label("Press [bold]s[/bold] to scan subnet for Raspberry Pis", id="subtitle")
        yield DataTable(id="disc-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("IP", "MAC", "Hostname", "Pi Version", "DB Status")

    @work(thread=True)
    def _do_scan(self) -> None:
        self.app.call_from_thread(
            self.query_one("#subtitle", Label).update,
            "[yellow]Scanning subnet… (may take 1–2 min)[/yellow]",
        )
        try:
            result = self._api.scan_discovery()
            self.app.call_from_thread(self._on_result, result)
        except ApiError as e:
            self.app.call_from_thread(
                self.query_one("#subtitle", Label).update,
                f"[red]Scan failed: {e}[/red]",
            )

    def _on_result(self, result: dict) -> None:
        discovered = result.get("discovered", [])
        added = result.get("added", 0)
        updated = result.get("updated", 0)
        status = result.get("status", "")

        table = self.query_one(DataTable)
        table.clear()
        for d in discovered:
            pi_ver = d.get("pi_version")
            table.add_row(
                d.get("ip", ""),
                d.get("mac", ""),
                d.get("hostname") or "—",
                f"Pi {pi_ver}" if pi_ver else "—",
                "[green]known[/green]" if updated else "[yellow]new[/yellow]",
            )

        color = "green" if status == "success" else "red"
        self.query_one("#subtitle", Label).update(
            f"[{color}]{status.upper()}[/{color}]  "
            f"{len(discovered)} found  •  {added} added  •  {updated} updated"
        )

    def action_scan(self) -> None:
        self._do_scan()

    def action_back(self) -> None:
        self.app.pop_screen()
