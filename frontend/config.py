import os

# The TUI is a local break-glass tool: it runs on the controller itself and talks
# to uvicorn directly (not through nginx), authenticated by the key file.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
TUI_KEY_FILE = os.environ.get("PI_CONTROLLER_TUI_KEY_FILE", "/opt/pi-controller/.tui-key")
