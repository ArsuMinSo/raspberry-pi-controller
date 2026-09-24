"""Parse Pi command output (no I/O): throttling flags, `df -P /` usage, reboot/sudo errors."""
import re

SEPARATOR = "__PIC_DIAG_SEP__"

# vcgencmd get_throttled bits — https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
_THROTTLED_BITS = {
    "under_voltage_now": 0,
    "freq_capped_now": 1,
    "throttled_now": 2,
    "soft_temp_limit_now": 3,
    "under_voltage_ever": 16,
    "freq_capped_ever": 17,
    "throttled_ever": 18,
    "soft_temp_limit_ever": 19,
}

# vcgencmd: "throttled=0x50005"; sysfs /sys/devices/platform/soc/soc:firmware/get_throttled: bare hex "50005"
_THROTTLED_RE = re.compile(r"throttled=0x([0-9a-fA-F]+)")
_BARE_HEX_RE = re.compile(r"^\s*([0-9a-fA-F]{1,8})\s*$")


def build_command(throttled_cmd: str, disk_cmd: str) -> str:
    """One SSH round-trip: both checks, outputs split by a separator line."""
    return f"export LC_ALL=C; {throttled_cmd} 2>&1; echo {SEPARATOR}; {disk_cmd} 2>&1"


def parse_throttled(text: str) -> dict:
    """`throttled=0x50005` (vcgencmd) or `50005` (sysfs) → {"raw": "0x50005", "ok": False, …}.

    ValueError if neither format is present.
    """
    text = text or ""
    m = _THROTTLED_RE.search(text) or _BARE_HEX_RE.match(text)
    if not m:
        raise ValueError(
            f"can't read throttling state (got {text.strip()[:80]!r}) — the Pi user may need the `video` group"
        )
    value = int(m.group(1), 16)
    flags = {name: bool(value >> bit & 1) for name, bit in _THROTTLED_BITS.items()}
    return {"raw": hex(value), "ok": value == 0, **flags}


def parse_df(text: str) -> dict:
    """`df -P /` → {"used_percent": 42, "free_mb": 12345, "size_mb": …, "mount": "/"}. ValueError if unparseable."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for line in lines:
        parts = line.split()
        # Filesystem 1024-blocks Used Available Capacity Mounted-on (path may contain spaces → join the rest)
        if len(parts) >= 6 and parts[4].endswith("%") and parts[1].isdigit() and parts[3].isdigit():
            return {
                "used_percent": int(parts[4].rstrip("%")),
                "free_mb": int(parts[3]) // 1024,
                "size_mb": int(parts[1]) // 1024,
                "mount": " ".join(parts[5:]),
            }
    raise ValueError(f"unexpected df output: {(text or '').strip()[:80]!r}")


def parse_output(stdout: str) -> tuple[dict, str | None]:
    """Combined output of `build_command` → (details, error). Partial results are kept: a Pi without
    vcgencmd still reports disk usage, with the throttled problem in `error`."""
    throttled_text, _, disk_text = (stdout or "").partition(SEPARATOR)
    details: dict = {}
    errors: list[str] = []
    try:
        details["throttled"] = parse_throttled(throttled_text)
    except ValueError as e:
        errors.append(f"throttled: {e}")
    try:
        details["disk"] = parse_df(disk_text)
    except ValueError as e:
        errors.append(f"disk: {e}")
    return details, ("; ".join(errors) or None)


REBOOT_NOT_PERMITTED = "reboot not permitted for this SSH user (polkit/sudo) — see docs"

# English texts (commands run with LC_ALL=C); polkit/logind and sudo -n refusals
_PERMISSION_MARKERS = ("Interactive authentication required", "Access denied", "a password is required")


def reboot_error(stderr: str | None) -> str | None:
    """Per-Pi error for a failed reboot: permission refusals → one clear message, anything else → stderr."""
    text = (stderr or "").strip()
    if any(marker in text for marker in _PERMISSION_MARKERS):
        return REBOOT_NOT_PERMITTED
    return text[:500] or None
