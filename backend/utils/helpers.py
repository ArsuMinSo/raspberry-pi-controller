import re

_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
_POS_RE = re.compile(r"^\d{2}-\d{3}$")


def normalise_mac(mac: str) -> str:
    m = mac.lower().strip()
    if not _MAC_RE.match(m):
        raise ValueError(f"Invalid MAC address: {mac}")
    return m


def validate_position(position: str) -> str:
    p = position.strip()
    if not _POS_RE.match(p):
        raise ValueError(f"Invalid position format (expected XX-XXX): {position}")
    return p


def paginate(query, page: int, limit: int):
    return query.offset((page - 1) * limit).limit(limit)
