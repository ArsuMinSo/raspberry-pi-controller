import ipaddress

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label
from textual import work

from frontend.api_client import ApiClient, ApiError


def _range_to_from_to(scan_range: str) -> tuple[str, str]:
    """Parse stored range (CIDR or start-end) back into (from_ip, to_ip)."""
    scan_range = scan_range.strip()
    if not scan_range:
        return "", ""
    if "-" in scan_range and "/" not in scan_range:
        parts = scan_range.split("-", 1)
        return parts[0].strip(), parts[1].strip()
    try:
        net = ipaddress.ip_network(scan_range, strict=False)
        hosts = list(net.hosts())
        if hosts:
            return str(hosts[0]), str(hosts[-1])
        return str(net.network_address), str(net.broadcast_address)
    except ValueError:
        return scan_range, ""


class DiscoveryScreen(Screen):
    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    DiscoveryScreen {
        layout: vertical;
    }
    #range-row {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    .range-label {
        width: auto;
        padding: 0 1;
    }
    .range-input {
        width: 18;
    }
    #probe-check {
        width: auto;
        margin-left: 2;
    }
    #save-btn {
        width: auto;
        margin-left: 2;
    }
    #scan-btn {
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
        with Horizontal(id="range-row"):
            yield Label("From:", classes="range-label")
            yield Input(placeholder="10.10.30.1", id="from-ip", classes="range-input")
            yield Label("To:", classes="range-label")
            yield Input(placeholder="10.10.30.254", id="to-ip", classes="range-input")
            yield Checkbox("SSH probe", value=True, id="probe-check")
            yield Button("Save", variant="default", id="save-btn")
            yield Button("Scan  [s]", variant="primary", id="scan-btn")
            yield Label("", id="saved-note")
        yield Label("Set range and press Scan or [bold]s[/bold]", id="subtitle")
        yield DataTable(id="disc-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("IP", "MAC", "Hostname", "Pi Version")
        self._load_range()

    @work(thread=True)
    def _load_range(self) -> None:
        try:
            data = self._api.get_settings()
            net = data.get("network", {})
            stored = net.get("subnet", "")
            probe_ssh = net.get("probe_ssh", True)
            from_ip, to_ip = _range_to_from_to(stored)
            self.app.call_from_thread(self._set_range, from_ip, to_ip, probe_ssh)
        except ApiError:
            pass

    def _set_range(self, from_ip: str, to_ip: str, probe_ssh: bool) -> None:
        self.query_one("#from-ip", Input).value = from_ip
        self.query_one("#to-ip", Input).value = to_ip
        self.query_one("#probe-check", Checkbox).value = probe_ssh

    def _build_range_str(self) -> str | None:
        from_ip = self.query_one("#from-ip", Input).value.strip()
        to_ip = self.query_one("#to-ip", Input).value.strip()
        if not from_ip or not to_ip:
            self.notify("Enter both From and To IP addresses", severity="warning")
            return None
        try:
            ipaddress.IPv4Address(from_ip)
            ipaddress.IPv4Address(to_ip)
        except ValueError as e:
            self.notify(f"Invalid IP: {e}", severity="error")
            return None
        return f"{from_ip}-{to_ip}"

    def _probe_ssh(self) -> bool:
        return self.query_one("#probe-check", Checkbox).value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            r = self._build_range_str()
            if r:
                self._do_save(r, self._probe_ssh())
        elif event.button.id == "scan-btn":
            self.action_scan()

    @work(thread=True)
    def _do_save(self, scan_range: str, probe_ssh: bool) -> None:
        try:
            self._api.update_network_settings(scan_range, probe_ssh=probe_ssh)
            self.app.call_from_thread(
                self.query_one("#saved-note", Label).update, "[green]Saved[/green]"
            )
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_scan(self, scan_range: str, probe_ssh: bool) -> None:
        probe_note = "with SSH probe" if probe_ssh else "ping+ARP only"
        self.app.call_from_thread(
            self.query_one("#subtitle", Label).update,
            f"[yellow]Scanning {scan_range} ({probe_note}) …[/yellow]",
        )
        try:
            self._api.update_network_settings(scan_range, probe_ssh=probe_ssh)
            self.app.call_from_thread(
                self.query_one("#saved-note", Label).update, "[green]Saved[/green]"
            )
            result = self._api.scan_discovery()
            self.app.call_from_thread(self._on_result, result)
        except ApiError as e:
            self.app.call_from_thread(
                self.query_one("#subtitle", Label).update, f"[red]Scan failed: {e}[/red]"
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
        r = self._build_range_str()
        if r:
            self._do_scan(r, self._probe_ssh())

    def action_back(self) -> None:
        self.app.pop_screen()
