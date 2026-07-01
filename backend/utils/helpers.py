import re

import paramiko

_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_POS_RE = re.compile(r"^\d{2}-\d{3}$")
_PI_VERSION_RE = re.compile(r"raspberry pi (\d+)", re.IGNORECASE)

MAC_PLACEHOLDER = "00:00:00:00:00:00"


def normalise_mac(mac: str) -> str:
    m = mac.lower().strip()
    if not _MAC_RE.match(m):
        raise ValueError(f"Invalid MAC address: {mac}")
    return m


def is_valid_mac(mac: str) -> bool:
    return bool(_MAC_RE.match(mac))


def extract_pi_version(model_line: str) -> int | None:
    m = _PI_VERSION_RE.search(model_line)
    return int(m.group(1)) if m else None


def validate_position(position: str) -> str:
    p = position.strip()
    if not _POS_RE.match(p):
        raise ValueError(f"Invalid position format (expected XX-XXX): {position}")
    return p


def paginate(query, page: int, limit: int):
    return query.offset((page - 1) * limit).limit(limit)


_KEY_TYPES = (
    paramiko.RSAKey,
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
    paramiko.DSSKey,
)


def load_private_key(path: str) -> paramiko.PKey:
    """Load SSH private key, auto-detecting type (RSA, Ed25519, ECDSA, DSS)."""
    last_exc: Exception = Exception("no key types to try")
    for key_cls in _KEY_TYPES:
        try:
            return key_cls.from_private_key_file(path)
        except Exception as e:
            last_exc = e
    raise ValueError(f"Cannot load key from {path}: {last_exc}")
