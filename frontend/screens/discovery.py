import ipaddress

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Select
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.manage_pi import ManagePiScreen


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
        Binding("a", "add_to_db", "Add to DB"),
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
    #probe-row {
        height: 3;
        padding: 0 1;
        align: left middle;
        background: $surface;
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
    #probe-user {
        width: 16;
    }
    #probe-auth-select {
        width: 14;
        margin-left: 1;
    }
    #probe-pass {
        width: 18;
        margin-left: 1;
    }
    #probe-deploy {
        width: auto;
        margin-left: 2;
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
        self._discovered: list[dict] = []

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
        with Horizontal(id="probe-row"):
            yield Label("Probe:", classes="range-label")
            yield Label("User:", classes="range-label")
            yield Input(placeholder="pi", id="probe-user")
            yield Select(
                [("Key", "key"), ("Password", "password")],
                value="key",
                id="probe-auth-select",
                allow_blank=False,
            )
            yield Input(
                placeholder="password",
                id="probe-pass",
                password=True,
            )
            yield Checkbox("Deploy key", value=False, id="probe-deploy")
        yield Label("Set range and press Scan or [bold]s[/bold]", id="subtitle")
        yield DataTable(id="disc-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("IP", "Hostname", "Pi Version")
        self._load_settings()
        self._update_probe_row_visibility()

    @work(thread=True)
    def _load_settings(self) -> None:
        try:
            data = self._api.get_settings()
            net = data.get("network", {})
            stored = net.get("subnet", "")
            probe_ssh = net.get("probe_ssh", True)
            probe_username = net.get("probe_username", "")
            probe_auth = net.get("probe_auth", "key")
            probe_deploy_key = net.get("probe_deploy_key", False)
            from_ip, to_ip = _range_to_from_to(stored)
            self.app.call_from_thread(
                self._set_all_settings,
                from_ip, to_ip, probe_ssh, probe_username, probe_auth, probe_deploy_key,
            )
        except ApiError:
            pass

    def _set_all_settings(
        self,
        from_ip: str,
        to_ip: str,
        probe_ssh: bool,
        probe_username: str,
        probe_auth: str,
        probe_deploy_key: bool,
    ) -> None:
        self.query_one("#from-ip", Input).value = from_ip
        self.query_one("#to-ip", Input).value = to_ip
        self.query_one("#probe-check", Checkbox).value = probe_ssh
        if probe_username:
            self.query_one("#probe-user", Input).value = probe_username
        self.query_one("#probe-auth-select", Select).value = probe_auth
        self.query_one("#probe-deploy", Checkbox).value = probe_deploy_key
        self._update_probe_row_visibility()

    def _update_probe_row_visibility(self) -> None:
        probe_on = self.query_one("#probe-check", Checkbox).value
        self.query_one("#probe-row").display = probe_on
        auth = self._probe_auth()
        self.query_one("#probe-pass", Input).display = auth == "password"
        self.query_one("#probe-deploy", Checkbox).display = auth == "password"

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

    def _probe_auth(self) -> str:
        val = self.query_one("#probe-auth-select", Select).value
        return str(val) if val and val != Select.BLANK else "key"

    def _probe_username(self) -> str | None:
        v = self.query_one("#probe-user", Input).value.strip()
        return v or None

    def _probe_password(self) -> str | None:
        if self._probe_auth() != "password":
            return None
        v = self.query_one("#probe-pass", Input).value
        return v or None

    def _probe_deploy_key(self) -> bool:
        return self.query_one("#probe-deploy", Checkbox).value

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "probe-check":
            self._update_probe_row_visibility()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "probe-auth-select":
            self._update_probe_row_visibility()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            r = self._build_range_str()
            if r:
                self._do_save(r)
        elif event.button.id == "scan-btn":
            self.action_scan()

    @work(thread=True)
    def _do_save(self, scan_range: str) -> None:
        try:
            self._api.update_network_settings(
                scan_range,
                probe_ssh=self._probe_ssh(),
                probe_username=self._probe_username(),
                probe_auth=self._probe_auth(),
                probe_deploy_key=self._probe_deploy_key(),
            )
            self.app.call_from_thread(
                self.query_one("#saved-note", Label).update, "[green]Saved[/green]"
            )
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_scan(self, scan_range: str) -> None:
        probe_note = "with SSH probe" if self._probe_ssh() else "ping only"
        self.app.call_from_thread(
            self.query_one("#subtitle", Label).update,
            f"[yellow]Scanning {scan_range} ({probe_note}) …[/yellow]",
        )
        try:
            self._api.update_network_settings(
                scan_range,
                probe_ssh=self._probe_ssh(),
                probe_username=self._probe_username(),
                probe_auth=self._probe_auth(),
                probe_deploy_key=self._probe_deploy_key(),
            )
            self.app.call_from_thread(
                self.query_one("#saved-note", Label).update, "[green]Saved[/green]"
            )
            result = self._api.scan_discovery(probe_password=self._probe_password())
            self.app.call_from_thread(self._on_result, result)
        except ApiError as e:
            self.app.call_from_thread(
                self.query_one("#subtitle", Label).update, f"[red]Scan failed: {e}[/red]"
            )

    def _on_result(self, result: dict) -> None:
        self._discovered = result.get("discovered", [])
        added = result.get("added", 0)
        updated = result.get("updated", 0)
        status = result.get("status", "")

        table = self.query_one(DataTable)
        table.clear()
        for d in self._discovered:
            pi_ver = d.get("pi_version")
            table.add_row(
                d.get("ip", ""),
                d.get("hostname") or "—",
                f"Pi {pi_ver}" if pi_ver else "—",
            )

        color = "green" if status == "success" else "red"
        self.query_one("#subtitle", Label).update(
            f"[{color}]{status.upper()}[/{color}]  "
            f"{len(self._discovered)} found  •  {added} not in DB  •  {updated} updated  "
            f"([bold]a[/bold] = add row to DB)"
        )

    def action_scan(self) -> None:
        r = self._build_range_str()
        if r:
            self._do_scan(r)

    def action_add_to_db(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._discovered):
            self.notify("No row selected", severity="warning")
            return
        self._prepare_add(self._discovered[row])

    @work(thread=True)
    def _prepare_add(self, d: dict) -> None:
        import re
        try:
            pis = self._api.list_pis()
        except ApiError:
            pis = []
        used = {
            int(m.group(1))
            for pi in pis
            if (m := re.match(r"^00-(\d{3})$", pi.get("position", "")))
        }
        n = 1
        while n in used:
            n += 1
        prefill = {
            "position": f"00-{n:03d}",
            "ip": d.get("ip"),
            "hostname": d.get("hostname"),
            "pi_version": d.get("pi_version"),
        }
        self.app.call_from_thread(self._open_add_dialog, prefill)

    def _open_add_dialog(self, prefill: dict) -> None:
        def _on_result(data: dict | None) -> None:
            if data is None:
                return
            self._do_create_pi(data)

        self.app.push_screen(ManagePiScreen(prefill=prefill), _on_result)

    @work(thread=True)
    def _do_create_pi(self, data: dict) -> None:
        try:
            self._api.create_pi(**data)
            self.app.call_from_thread(self.notify, f"Added {data['position']} to DB")
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    def action_back(self) -> None:
        self.app.pop_screen()
