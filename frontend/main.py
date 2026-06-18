import sys

from textual.app import App, ComposeResult
from textual.binding import Binding

from frontend.api_client import ApiClient
from frontend.config import BACKEND_URL
from frontend.screens.execute import ExecuteScreen
from frontend.screens.health import HealthScreen
from frontend.screens.home import HomeScreen
from frontend.screens.logs import LogsScreen


class PiController(App):
    TITLE = "Pi Controller"
    SUB_TITLE = f"backend: {BACKEND_URL}"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

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
            elif screen == "health" and home is not None:
                super().push_screen(HealthScreen(self._api, home.selected))
            elif screen == "logs":
                super().push_screen(LogsScreen(self._api))
        else:
            super().push_screen(screen, *args, **kwargs)


def main() -> None:
    api = ApiClient(BACKEND_URL)
    app = PiController(api)
    app.run()


if __name__ == "__main__":
    main()
