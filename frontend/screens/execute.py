import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Checkbox, DataTable, Footer, Header, Input, Label
from textual.binding import Binding
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.detail import DetailScreen
from frontend.utils.formatters import truncate


_COLUMNS = [
    ("Position", 12),
    ("Exit",      6),
    ("Stdout",   50),
    ("Stderr",   30),
    ("Error",    30),
]

_SORT_KEYS = [
    lambda r: (r.get("position") or "").lower(),
    lambda r: r.get("exit_code") if r.get("exit_code") is not None else -1,
    lambda r: (r.get("stdout") or "").lower(),
    lambda r: (r.get("stderr") or "").lower(),
    lambda r: (r.get("error") or "").lower(),
]


class ExecuteScreen(Screen):
    BINDINGS = [
        Binding("v", "detail", "View detail"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    ExecuteScreen {
        layout: vertical;
    }
    #selected-pis {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }
    #cmd-label {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #cmd-row {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    #cmd-input {
        width: 1fr;
    }
    #sudo-check {
        width: auto;
        margin-left: 2;
    }
    #sudo-pass {
        width: 20;
        margin-left: 1;
        display: none;
    }
    #detach-check {
        width: auto;
        margin-left: 2;
    }
    #results-label {
        height: 1;
        padding: 0 1;
        margin-top: 1;
        color: $text-muted;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, api: ApiClient, selected: set[str]):
        super().__init__()
        self._api = api
        self._selected = sorted(selected)
        self._results: list[dict] = []
        self._sort_col: int | None = None
        self._sort_asc: bool = True
        self._parallel_limit = 10  # overwritten from Settings once loaded

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            f"Selected ({len(self._selected)}): {', '.join(self._selected)}",
            id="selected-pis",
        )
        yield Label("Command:", id="cmd-label")
        with Horizontal(id="cmd-row"):
            yield Input(placeholder="e.g. uptime", id="cmd-input")
            yield Checkbox("Sudo", id="sudo-check")
            yield Input(placeholder="sudo password", id="sudo-pass", password=True)
            yield Checkbox("Detach", id="detach-check")
        yield Label("Results: (v or Enter on row for full output)", id="results-label")
        yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._redraw_table()
        self.query_one("#cmd-input", Input).focus()
        self._load_parallel_limit()

    @work(thread=True)
    def _load_parallel_limit(self) -> None:
        try:
            n = int(self._api.get_settings().get("ssh", {}).get("parallel_limit") or 10)
        except (ApiError, ValueError, TypeError):
            return
        self._parallel_limit = max(1, n)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "sudo-check":
            self.query_one("#sudo-pass", Input).display = event.value

    def _build_command(self, raw: str) -> str:
        """Must be called from the main thread (accesses widgets)."""
        # Detach: background the command so SSH returns before it finishes.
        # Needed for reboot/shutdown/long-running commands.
        if self.query_one("#detach-check", Checkbox).value:
            b64_inner = base64.b64encode(raw.encode()).decode()
            raw = (
                f"nohup bash -c \"$(echo {b64_inner} | base64 -d)\" "
                f"</dev/null &>/dev/null & disown; sleep 0.5"
            )

        if not self.query_one("#sudo-check", Checkbox).value:
            return raw

        password = self.query_one("#sudo-pass", Input).value
        if password:
            escaped_pass = password.replace("'", "'\\''")
            # Write command to a temp script file so <<< / $'...' / heredocs
            # in the user command don't conflict with the password pipe to sudo -S.
            b64 = base64.b64encode(raw.encode()).decode()
            return (
                f"_T=$(mktemp) && "
                f"echo '{b64}' | base64 -d > \"$_T\" && "
                f"echo '{escaped_pass}' | sudo -S bash \"$_T\"; "
                f"_R=$?; rm -f \"$_T\"; exit $_R"
            )
        return f"sudo {raw}"

    def _apply_sort(self) -> None:
        if self._sort_col is not None and _SORT_KEYS[self._sort_col] is not None:
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
            ec = r.get("exit_code")
            table.add_row(
                r.get("position", ""),
                str(ec) if ec is not None else "—",
                truncate(r.get("stdout"), 60),
                truncate(r.get("stderr"), 40),
                r.get("error") or "",
                key=r.get("position"),
            )

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        col = event.column_index
        if _SORT_KEYS[col] is None:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_sort()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd-input":
            return
        raw = event.value.strip()
        if not raw:
            return
        command = self._build_command(raw)  # main thread — safe widget access
        self._run_command(raw, command)

    @work(thread=True)
    def _run_command(self, raw: str, command: str) -> None:
        self.app.call_from_thread(self._set_running, raw)
        total = len(self._selected)
        done = 0
        ok_count = 0

        def _exec_one(pos: str) -> tuple[str, dict | None]:
            try:
                resp = self._api.execute_command([pos], command)
                return pos, self._api.get_command_result(resp["action_id"])
            except ApiError:
                return pos, None

        with ThreadPoolExecutor(max_workers=max(1, min(self._parallel_limit, total))) as ex:
            futures = {ex.submit(_exec_one, pos): pos for pos in self._selected}
            for future in as_completed(futures):
                pos, result = future.result()
                done += 1
                if result:
                    for r in result.get("results", []):
                        self._results.append(r)
                    if result.get("status") == "success":
                        ok_count += 1
                self.app.call_from_thread(self._update_exec_bar, done, total, pos)
                self.app.call_from_thread(self._apply_sort)

        self.app.call_from_thread(self._on_exec_done, ok_count, total)

    def _set_running(self, raw: str) -> None:
        sudo_note = " [yellow][sudo][/yellow]" if self.query_one("#sudo-check", Checkbox).value else ""
        detach_note = " [dim][detach][/dim]" if self.query_one("#detach-check", Checkbox).value else ""
        self.query_one("#results-label", Label).update(
            f"[yellow]Executing:{sudo_note}{detach_note}[/yellow] {raw}"
        )
        self._results = []
        self._redraw_table()
        self.query_one("#cmd-input", Input).disabled = True

    def _update_exec_bar(self, done: int, total: int, last: str) -> None:
        pct = done / total if total > 0 else 0
        filled = int(30 * pct)
        bar = "█" * filled + "░" * (30 - filled)
        self.query_one("#results-label", Label).update(
            f"[yellow][{bar}] {done}/{total}  ✓ {last}[/yellow]"
        )

    def _on_exec_done(self, ok: int, total: int) -> None:
        color = "green" if ok == total else ("red" if ok == 0 else "yellow")
        self.query_one("#results-label", Label).update(
            f"[{color}][{'█' * 30}] {ok}/{total} OK[/{color}]  (Enter on row for full output)"
        )
        self.query_one("#cmd-input", Input).disabled = False
        self.query_one("#cmd-input", Input).clear()
        self.query_one("#cmd-input", Input).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_detail()

    def _on_error(self, msg: str) -> None:
        self.query_one("#results-label", Label).update(f"[red]Error: {msg}[/red]")
        self.query_one("#cmd-input", Input).disabled = False
        self.query_one("#cmd-input", Input).focus()

    def action_detail(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        pos = r.get("position", "?")
        ec = r.get("exit_code")
        meta = [
            ("Position", pos),
            ("Exit code", str(ec) if ec is not None else "—"),
            ("Error", r.get("error") or "—"),
        ]
        stdout = r.get("stdout") or ""
        stderr = r.get("stderr") or ""
        body = ""
        if stdout:
            body += "─── STDOUT ─────────────────────────────────────────\n"
            body += stdout.rstrip() + "\n"
        if stderr:
            body += "\n─── STDERR ─────────────────────────────────────────\n"
            body += stderr.rstrip() + "\n"
        if not body:
            body = "(no output)"
        self.app.push_screen(DetailScreen(f"Result: {pos}", meta, body))

    def action_back(self) -> None:
        self.app.pop_screen()
