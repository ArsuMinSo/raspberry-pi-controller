from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label
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
    #subnet-row {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    #subnet-label {
        width: auto;
        padding: 0 1;
    }
    #subnet-input {
        width: 28;
    }
    #save-btn {
        width: auto;
        margin-left: 1;
    }
    #saved-note {
        width: auto;
        margin-left: 1;
        color: $text-muted;
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
        with Horizontal(id="subnet-row"):
            yield Label("Subnet:", id="subnet-label")
            yield Input(placeholder="10.10.20.0/24", id="subnet-input")
            yield Button("Save", variant="default", id="save-btn")
            yield Label("", id="saved-note")
        yield Label("Press [bold]s[/bold] to scan", id="subtitle")
        yield DataTable(id="disc-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("IP", "MAC", "Hostname", "Pi Version")
        self._load_subnet()

    @work(thread=True)
    def _load_subnet(self) -> None:
        try:
            data = self._api.get_settings()
            subnet = data.get("network", {}).get("subnet", "")
            self.app.call_from_thread(self._set_subnet, subnet)
        except ApiError:
            pass

    def _set_subnet(self, subnet: str) -> None:
        self.query_one("#subnet-input", Input).value = subnet

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_subnet()

    def _save_subnet(self) -> None:
        subnet = self.query_one("#subnet-input", Input).value.strip()
        if not subnet:
            self.notify("Enter a subnet first", severity="warning")
            return
        self._do_save_subnet(subnet)

    @work(thread=True)
    def _do_save_subnet(self, subnet: str) -> None:
        try:
            self._api.update_network_settings(subnet)
            self.app.call_from_thread(
                self.query_one("#saved-note", Label).update,
                "[green]Saved[/green]",
            )
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_scan(self) -> None:
        subnet = self.query_one("#subnet-input", Input).value.strip()

        # Save subnet before scanning if it differs from config
        if subnet:
            try:
                self._api.update_network_settings(subnet)
                self.app.call_from_thread(
                    self.query_one("#saved-note", Label).update,
                    "[green]Saved[/green]",
                )
            except ApiError:
                pass

        self.app.call_from_thread(
            self.query_one("#subtitle", Label).update,
            f"[yellow]Scanning {subnet or '…'} (may take 1–2 min)[/yellow]",
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
