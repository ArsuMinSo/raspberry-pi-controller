import getpass
import os
import signal
import sys
from pathlib import Path

# allow `python frontend/main.py` in addition to `python -m frontend.main`
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from textual.app import App, ComposeResult
from textual.binding import Binding

from frontend.api_client import ApiClient
from frontend.config import BACKEND_URL, TUI_KEY_FILE
from frontend.screens.discovery import DiscoveryScreen
from frontend.screens.execute import ExecuteScreen
from frontend.screens.home import HomeScreen
from frontend.screens.logs import LogsScreen
from frontend.screens.scheduled_tasks import ScheduledTasksScreen


class PiController(App):
    TITLE = "Pi Controller"
    SUB_TITLE = f"backend: {BACKEND_URL}"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "noop", show=False, priority=True),
    ]

    def action_noop(self) -> None:
        pass

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, api: ApiClient):
        super().__init__()
        self._api = api
        self._home: HomeScreen | None = None

    def on_mount(self) -> None:
        self._home = HomeScreen(self._api)
        self.push_screen(self._home)

    def push_screen(self, screen, *args, **kwargs):
        if isinstance(screen, str):
            home = self._home
            if screen == "execute" and home is not None:
                super().push_screen(ExecuteScreen(self._api, home.selected))
            elif screen == "logs":
                super().push_screen(LogsScreen(self._api, home.selected if home else set()))
            elif screen == "discovery":
                super().push_screen(DiscoveryScreen(self._api))
            elif screen == "tasks":
                super().push_screen(ScheduledTasksScreen(self._api))
        else:
            super().push_screen(screen, *args, **kwargs)


def _read_local_key() -> str:
    try:
        with open(TUI_KEY_FILE) as f:
            key = f.read().strip()
    except PermissionError:
        sys.exit(f"Can't read the TUI key {TUI_KEY_FILE} — run the TUI on the server with sudo:\n"
                 f"    sudo .venv/bin/python -m frontend.main")
    except FileNotFoundError:
        sys.exit(f"TUI key {TUI_KEY_FILE} not found — run scripts/deploy.sh on this server first\n"
                 f"(or set PI_CONTROLLER_TUI_KEY_FILE).")
    if not key:
        sys.exit(f"TUI key {TUI_KEY_FILE} is empty — rotate it: python -m backend.manage rotate-tui-key")
    return key


def main() -> None:
    key = _read_local_key()
    unix_user = os.environ.get("SUDO_USER") or getpass.getuser()  # shown in the activity log
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    api = ApiClient(BACKEND_URL, key, unix_user)
    app = PiController(api)
    app.run()


if __name__ == "__main__":
    main()
