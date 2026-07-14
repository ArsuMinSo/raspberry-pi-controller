from datetime import datetime


def fmt_datetime(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return dt_str[:16] if dt_str else "—"


def fmt_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "—"


def fmt_uptime(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def fmt_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def truncate(s: str | None, width: int) -> str:
    if s is None:
        return "—"
    s = str(s)
    if len(s) <= width:
        return s
    return s[: width - 1] + "…"


def status_markup(status: str) -> str:
    if status == "reachable":
        return f"[green]{status}[/green]"
    return f"[red]{status}[/red]"
