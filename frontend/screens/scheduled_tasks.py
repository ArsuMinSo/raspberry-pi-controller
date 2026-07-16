from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual import work

from frontend.api_client import ApiClient, ApiError
from frontend.screens.confirm import ConfirmScreen
from frontend.screens.manage_task import ManageTaskScreen
from frontend.utils.formatters import fmt_datetime


_COLUMNS = [
    ("", 2),
    ("Name", 24),
    ("Type", 12),
    ("Cron", 18),
    ("Pis", 20),
    ("Last Run", 22),
    ("Last Status", 14),
]


class ScheduledTasksScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_task", "New"),
        Binding("e", "edit_task", "Edit"),
        Binding("d", "delete_task", "Delete"),
        Binding("space", "toggle_enabled", "Enable/Disable"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    ScheduledTasksScreen {
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
        self._tasks: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading…", id="subtitle")
        yield DataTable(id="task-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._init_table()
        self.load_tasks()

    def _init_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for label, width in _COLUMNS:
            table.add_column(label, width=width)

    @work(thread=True)
    def load_tasks(self) -> None:
        try:
            tasks = self._api.list_tasks()
        except ApiError as e:
            self.app.call_from_thread(self._set_subtitle, f"[red]Error: {e}[/red]")
            return
        self.app.call_from_thread(self._on_loaded, tasks)

    def _on_loaded(self, tasks: list[dict]) -> None:
        self._tasks = tasks
        self._redraw_table()
        enabled = sum(1 for t in tasks if t.get("enabled"))
        self._set_subtitle(f"{len(tasks)} task(s) — {enabled} enabled  [Space]=toggle  [n]=new  [e]=edit  [d]=delete")

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for label, width in _COLUMNS:
            table.add_column(label, width=width)
        for t in self._tasks:
            enabled = t.get("enabled", False)
            pis = t.get("pis") or []
            pis_str = ", ".join(pis[:3]) + ("…" if len(pis) > 3 else "") if pis else "[dim]all[/dim]"
            last_status = t.get("last_status") or "—"
            status_color = {"success": "green", "fail": "red"}.get(last_status, "white")
            table.add_row(
                "[green]●[/green]" if enabled else "[red]○[/red]",
                t.get("name", ""),
                t.get("task_type", ""),
                t.get("cron", ""),
                pis_str,
                fmt_datetime(t.get("last_run")),
                f"[{status_color}]{last_status}[/{status_color}]",
                key=str(t.get("id")),
            )

    def _set_subtitle(self, msg: str) -> None:
        self.query_one("#subtitle", Label).update(msg)

    def _current_task(self) -> dict | None:
        table = self.query_one(DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._tasks):
            return None
        return self._tasks[table.cursor_row]

    def action_refresh(self) -> None:
        self._set_subtitle("Refreshing…")
        self.load_tasks()

    def action_new_task(self) -> None:
        def _on_result(data: dict | None) -> None:
            if data is None:
                return
            self._do_create(data)

        self.app.push_screen(ManageTaskScreen(), _on_result)

    def action_edit_task(self) -> None:
        task = self._current_task()
        if task is None:
            self.notify("No task selected", severity="warning")
            return

        def _on_result(data: dict | None) -> None:
            if data is None:
                return
            self._do_update(task["id"], data)

        self.app.push_screen(ManageTaskScreen(task=task), _on_result)

    def action_delete_task(self) -> None:
        task = self._current_task()
        if task is None:
            self.notify("No task selected", severity="warning")
            return

        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._do_delete(task["id"])

        self.app.push_screen(
            ConfirmScreen(f"Delete task [bold]{task['name']}[/bold]?", title="Delete Task", confirm_label="Delete  [Enter]"),
            _on_confirm,
        )

    def action_toggle_enabled(self) -> None:
        task = self._current_task()
        if task is None:
            return
        self._do_update(task["id"], {"enabled": not task.get("enabled", True)})

    @work(thread=True)
    def _do_create(self, data: dict) -> None:
        try:
            self._api.create_task(**data)
            self.app.call_from_thread(self.notify, f"Created task '{data['name']}'")
            self.app.call_from_thread(self.load_tasks)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_update(self, task_id: int, data: dict) -> None:
        try:
            self._api.update_task(task_id, **data)
            self.app.call_from_thread(self.load_tasks)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True)
    def _do_delete(self, task_id: int) -> None:
        try:
            self._api.delete_task(task_id)
            self.app.call_from_thread(self.notify, "Task deleted")
            self.app.call_from_thread(self.load_tasks)
        except ApiError as e:
            self.app.call_from_thread(self.notify, str(e), severity="error")

    def action_back(self) -> None:
        self.app.pop_screen()
