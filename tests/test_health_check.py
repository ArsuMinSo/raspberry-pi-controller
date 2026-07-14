from unittest.mock import MagicMock, patch

from backend.config import SSHSettings
from backend.services.health_check import _parse_uptime, check_health

SETTINGS = SSHSettings(
    private_key_path="/fake/key",
    username="pi",
    timeout_s=5,
    retry_count=1,
    retry_delay_s=0,
    parallel_limit=10,
)

_FAKE_OUTPUTS = {
    "cat /proc/loadavg": "0.10 0.20 0.30 1/200 123",
    "nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo": "4",
    "awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} "
    "END{if(t>0) printf \"%.1f\", (t-a)/t*100}' /proc/meminfo": "42.5",
    "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null": "45000",
    "hostname": "kiosk01",
    "ip link show | awk '/link\\/ether/{print $2; exit}'": "b8:27:eb:aa:bb:cc",
    "cat /proc/cpuinfo": "Model : Raspberry Pi 4 Model B\nSerial : deadbeef",
    "date -u +%Y-%m-%dT%H:%M:%S": "2026-07-14T10:30:00",
    "cat /proc/uptime": "543210.12 400000.00",
}


def _fake_exec_command(cmd, timeout=None):
    out = _FAKE_OUTPUTS.get(cmd.strip(), "")
    stdout_fh = MagicMock()
    stdout_fh.read.return_value = out.encode()
    return None, stdout_fh, MagicMock()


def test_parse_uptime():
    assert _parse_uptime("123456.78 98765.43\n") == 123456
    assert _parse_uptime("") is None
    assert _parse_uptime("garbage") is None


@patch("backend.services.health_check.load_private_key", return_value=None)
@patch("backend.services.health_check._ping", return_value=True)
@patch("backend.services.health_check.paramiko.SSHClient")
def test_check_health_collects_pi_time_and_uptime(mock_client_cls, mock_ping, mock_key):
    client = MagicMock()
    client.exec_command.side_effect = _fake_exec_command
    mock_client_cls.return_value = client

    data = check_health("10.10.20.5", "01-001", SETTINGS)

    assert data.result.error is None
    assert data.result.pi_time == "2026-07-14T10:30:00Z"
    assert data.result.uptime_s == 543210
    assert data.result.cpu_1m is not None
    assert data.result.temp_c == 45.0


@patch("backend.services.health_check._ping", return_value=False)
def test_check_health_unreachable_has_no_time_or_uptime(mock_ping):
    data = check_health("10.10.20.5", "01-001", SETTINGS)
    assert data.result.error is not None
    assert data.result.pi_time is None
    assert data.result.uptime_s is None
