"""Diagnostics parsing + fleet command config (no DB, no SSH)."""
import pytest

from backend.config import PiCommands, _load
from backend.services import diagnostics as d

DF_OK = """Filesystem     1024-blocks    Used Available Capacity Mounted on
/dev/root         30375756 8123456  20889012      29% /
"""


def test_throttled_clean():
    r = d.parse_throttled("throttled=0x0\n")
    assert r["ok"] is True and r["raw"] == "0x0"
    assert not any(v for k, v in r.items() if k not in ("ok", "raw"))


def test_throttled_undervoltage_now_and_ever():
    r = d.parse_throttled("throttled=0x50005")
    assert r["ok"] is False
    assert r["under_voltage_now"] and r["throttled_now"]
    assert r["under_voltage_ever"] and r["throttled_ever"]
    assert not r["freq_capped_now"] and not r["soft_temp_limit_now"]


def test_throttled_soft_temp_limit():
    r = d.parse_throttled("throttled=0x80008")
    assert r["soft_temp_limit_now"] and r["soft_temp_limit_ever"]
    assert not r["under_voltage_now"] and not r["under_voltage_ever"]


@pytest.mark.parametrize("text, raw, uv_now, uv_ever, soft_now", [
    ("0\n", "0x0", False, False, False),        # sysfs, clean
    ("50005", "0x50005", True, True, False),
    ("80008\n", "0x80008", False, False, True),
])
def test_throttled_sysfs_bare_hex(text, raw, uv_now, uv_ever, soft_now):
    r = d.parse_throttled(text)
    assert r["raw"] == raw and r["ok"] is (raw == "0x0")
    assert (r["under_voltage_now"], r["under_voltage_ever"], r["soft_temp_limit_now"]) == (uv_now, uv_ever, soft_now)


@pytest.mark.parametrize("text", [
    "", "bash: vcgencmd: command not found", "throttled=zz", None,
    "VCHI initialization failed\nCan't open device file: /dev/vcio",
])
def test_throttled_garbage(text):
    with pytest.raises(ValueError, match="video"):
        d.parse_throttled(text)


def test_df_ok():
    r = d.parse_df(DF_OK)
    assert r == {"used_percent": 29, "free_mb": 20889012 // 1024, "size_mb": 30375756 // 1024, "mount": "/"}


def test_df_garbage():
    with pytest.raises(ValueError):
        d.parse_df("df: /: No such file or directory")


def test_parse_output_combined():
    out = "throttled=0x50000\n" + d.SEPARATOR + "\n" + DF_OK
    details, error = d.parse_output(out)
    assert error is None
    assert details["throttled"]["under_voltage_ever"] and not details["throttled"]["under_voltage_now"]
    assert details["disk"]["used_percent"] == 29


def test_parse_output_partial_keeps_disk():
    out = "bash: vcgencmd: command not found\n" + d.SEPARATOR + "\n" + DF_OK
    details, error = d.parse_output(out)
    assert "throttled" not in details and details["disk"]["used_percent"] == 29
    assert error.startswith("throttled:")


def test_parse_output_empty():
    details, error = d.parse_output("")
    assert details == {} and "throttled:" in error and "disk:" in error


def test_parse_output_sysfs_format():
    details, error = d.parse_output("50005\n" + d.SEPARATOR + "\n" + DF_OK)
    assert error is None and details["throttled"]["under_voltage_now"]


@pytest.mark.parametrize("stderr, expected", [
    ("sudo: a password is required\n", d.SUDO_PASSWORD_ERROR),
    ("Failed to start transient timer unit", None),
    ("", None),
    (None, None),
])
def test_reboot_error(stderr, expected):
    assert d.reboot_error(stderr) == expected


def test_build_command_single_round_trip():
    cmd = d.build_command("vcgencmd get_throttled", "df -P /")
    assert cmd == f"vcgencmd get_throttled 2>&1; echo {d.SEPARATOR}; df -P / 2>&1"


# ─── config: pi_commands is optional ──────────────────────────────────────────

_BASE = """database: {host: h, port: 5432, user: u, password: p, db_name: d, pool_size: 1}
ssh: {private_key_path: k, username: pi, timeout_s: 1, retry_count: 1, retry_delay_s: 0, parallel_limit: 1}
network: {subnet: 10.10.20.0/24, scan_interval_s: 1}
server: {host: 127.0.0.1, port: 8000, log_level: INFO, workers: 1}
"""


def test_config_without_pi_commands_uses_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_BASE)
    assert _load(str(path)).pi_commands == PiCommands()


def test_config_partial_pi_commands(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_BASE + "pi_commands:\n  disk: df -P /data\n  throttled: ''\n  display_on: x\n")
    cmds = _load(str(path)).pi_commands  # old/unknown keys (display_on) ignored
    assert cmds.disk == "df -P /data"
    assert cmds.throttled == PiCommands().throttled  # empty → default
    assert cmds.reboot == PiCommands().reboot


def test_throttled_default_prefers_sysfs():
    assert PiCommands().throttled.startswith("cat /sys/devices/platform/soc/soc:firmware/get_throttled")


def test_reboot_default_returns_before_shutdown():
    assert "systemd-run --on-active" in PiCommands().reboot and "sudo -n" in PiCommands().reboot
