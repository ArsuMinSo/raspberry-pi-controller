import ipaddress
import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Select
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.manage_pi import ManagePiScreen


_BASE_HEADERS = ("", "IP", "Hostname", "Pi Version", "MAC")

_SORT_KEYS = [
    None,
    lambda d: _ip_sort_key(d.get("ip")),
    lambda d: (d.get("hostname") or "").lower(),
    lambda d: d.get("pi_version") or 0,
    lambda d: (d.get("mac") or "").lower(),
]


def _ip_sort_key(ip: str | None) -> tuple:
    if not ip:
        return (999, 999, 999, 999)
    try:
        return tuple(int(part) for part in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)


def _range_to_from_to(scan_range: str) -> tuple[str, str]:
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
        Binding("space", "toggle_select", "Select", show=True),
        Binding("a", "add", "Add"),
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
        self._selected: set[str] = set()  # keyed by IP
        self._sort_col: int | None = None
        self._sort_asc: bool = True

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
            yield Input(placeholder="password", id="probe-pass", password=True)
            yield Checkbox("Deploy key", value=False, id="probe-deploy")
        yield Label("Set range and press Scan or [bold]s[/bold]", id="subtitle")
        yield DataTable(id="disc-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._redraw_table()
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

    def _apply_sort(self) -> None:
        if self._sort_col is not None and _SORT_KEYS[self._sort_col] is not None:
            self._discovered.sort(key=_SORT_KEYS[self._sort_col], reverse=not self._sort_asc)
        self._redraw_table()

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        headers = list(_BASE_HEADERS)
        if self._sort_col is not None:
            headers[self._sort_col] += " ▲" if self._sort_asc else " ▼"
        table.add_columns(*headers)
        for d in self._discovered:
            ip = d.get("ip", "")
            pi_ver = d.get("pi_version")
            table.add_row(
                "✓" if ip in self._selected else " ",
                ip,
                d.get("hostname") or "—",
                f"Pi {pi_ver}" if pi_ver else "—",
                d.get("mac") or "—",
            )

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
        self._selected.clear()
        added = result.get("added", 0)
        updated = result.get("updated", 0)
        status = result.get("status", "")

        if self._sort_col is not None and _SORT_KEYS[self._sort_col] is not None:
            self._discovered.sort(key=_SORT_KEYS[self._sort_col], reverse=not self._sort_asc)
        self._redraw_table()

        color = "green" if status == "success" else "red"
        self.query_one("#subtitle", Label).update(
            f"[{color}]{status.upper()}[/{color}]  "
            f"{len(self._discovered)} found  •  {added} not in DB  •  {updated} updated  "
            f"  [Space]=select  [bold]a[/bold]=add"
        )

    def _refresh_subtitle(self) -> None:
        n = len(self._discovered)
        sel = len(self._selected)
        color = "green" if n else "white"
        self.query_one("#subtitle", Label).update(
            f"[{color}]{n} found[/{color}]"
            + (f"  [bold]{sel} selected[/bold]" if sel else "")
            + "  [Space]=select  [bold]a[/bold]=add"
        )

    def action_toggle_select(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._discovered):
            return
        ip = self._discovered[row].get("ip", "")
        if ip in self._selected:
            self._selected.discard(ip)
        else:
            self._selected.add(ip)
        table.update_cell_at((row, 0), "✓" if ip in self._selected else " ")
        self._refresh_subtitle()

    def action_scan(self) -> None:
        r = self._build_range_str()
        if r:
            self._do_scan(r)

    def action_add(self) -> None:
        if self._selected:
            self._prepare_bulk_add()
        else:
            table = self.query_one(DataTable)
            row = table.cursor_row
            if row < 0 or row >= len(self._discovered):
                self.notify("No row selected", severity="warning")
                return
            self._prepare_single_add(self._discovered[row])

    # ── Single add (opens form) ────────────────────────────────────────────────

    @work(thread=True)
    def _prepare_single_add(self, d: dict) -> None:
        try:
            pis = self._api.list_pis()
        except ApiError:
            pis = []
        position = _next_free_position(pis)
        prefill = {
            "position": position,
            "ip": d.get("ip"),
            "hostname": d.get("hostname"),
            "pi_version": d.get("pi_version"),
            "mac": d.get("mac"),
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

    # ── Bulk add (no form) ────────────────────────────────────────────────────

    @work(thread=True)
    def _prepare_bulk_add(self) -> None:
        try:
            pis = self._api.list_pis()
        except ApiError:
            pis = []

        used_slots = _used_00_slots(pis)
        existing_macs = {
            p["mac"].lower()
            for p in pis
            if p.get("mac") and p["mac"] != "00:00:00:00:00:00"
        }

        items = []
        n = 1
        for d in self._discovered:
            if d.get("ip", "") not in self._selected:
                continue
            while n in used_slots:
                n += 1
            position = f"00-{n:03d}"
            used_slots.add(n)
            n += 1

            mac = d.get("mac") or "00:00:00:00:00:00"
            items.append({
                "position": position,
                "mac": mac,
                "hostname": d.get("hostname"),
                "ip": d.get("ip"),
                "pi_version": d.get("pi_version"),
                "tags": [],
                "status": "reachable" if d.get("hostname") or d.get("ip") else "unreachable",
            })

        if not items:
            self.app.call_from_thread(self.notify, "Nothing to add", severity="warning")
            return

        try:
            result = self._api.bulk_create_pis(items)
            self.app.call_from_thread(self._on_bulk_result, result)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    def _on_bulk_result(self, result: dict) -> None:
        created = result.get("created", 0)
        skipped = result.get("skipped", 0)
        skip_reasons = [
            r["reason"] for r in result.get("results", []) if r.get("skipped") and r.get("reason")
        ]
        msg = f"Bulk add: {created} created, {skipped} skipped"
        if skip_reasons:
            msg += "\n" + "\n".join(skip_reasons)
        severity = "information" if created > 0 else "warning"
        self.notify(msg, severity=severity)
        self._selected.clear()
        self._refresh_subtitle()

    def action_back(self) -> None:
        self.app.pop_screen()


def _used_00_slots(pis: list[dict]) -> set[int]:
    used = set()
    for pi in pis:
        m = re.match(r"^00-(\d{3})$", pi.get("position", ""))
        if m:
            used.add(int(m.group(1)))
    return used


def _next_free_position(pis: list[dict]) -> str:
    used = _used_00_slots(pis)
    n = 1
    while n in used:
        n += 1
    return f"00-{n:03d}"
