"""Parse Pi diagnostics output (no I/O): `vcgencmd get_throttled` flags and `df -P /` usage."""
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

_THROTTLED_RE = re.compile(r"throttled=(0x[0-9a-fA-F]+)")


def build_command(throttled_cmd: str, disk_cmd: str) -> str:
    """One SSH round-trip: both checks, outputs split by a separator line."""
    return f"{throttled_cmd} 2>&1; echo {SEPARATOR}; {disk_cmd} 2>&1"


def parse_throttled(text: str) -> dict:
    """`throttled=0x50005` → {"raw": "0x50005", "ok": False, "under_voltage_now": True, …}. ValueError if absent."""
    m = _THROTTLED_RE.search(text or "")
    if not m:
        raise ValueError(f"unexpected get_throttled output: {(text or '').strip()[:80]!r}")
    value = int(m.group(1), 16)
    flags = {name: bool(value >> bit & 1) for name, bit in _THROTTLED_BITS.items()}
    return {"raw": m.group(1).lower(), "ok": value == 0, **flags}


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
