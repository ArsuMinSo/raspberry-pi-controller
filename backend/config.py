import functools
import os
import re
from dataclasses import dataclass

import yaml

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate(value):
    if isinstance(value, str):
        def _replace(m):
            var = m.group(1)
            if var not in os.environ:
                raise RuntimeError(f"Missing required env var: {var}")
            return os.environ[var]
        return _ENV_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(i) for i in value]
    return value


@dataclass
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    db_name: str
    pool_size: int


@dataclass
class SSHSettings:
    private_key_path: str
    username: str
    timeout_s: int
    retry_count: int
    retry_delay_s: int
    parallel_limit: int


@dataclass
class NetworkSettings:
    subnet: str
    scan_interval_s: int


@dataclass
class ServerSettings:
    host: str
    port: int
    log_level: str
    workers: int


@dataclass
class Settings:
    database: DatabaseSettings
    ssh: SSHSettings
    network: NetworkSettings
    server: ServerSettings


def _load(path: str = "config.yaml") -> Settings:
    with open(path) as f:
        raw = yaml.safe_load(f)
    raw = _interpolate(raw)

    db = raw["database"]
    ssh = raw["ssh"]
    net = raw["network"]
    srv = raw["server"]

    return Settings(
        database=DatabaseSettings(
            host=db["host"],
            port=int(db["port"]),
            user=db["user"],
            password=db["password"],
            db_name=db["db_name"],
            pool_size=int(db["pool_size"]),
        ),
        ssh=SSHSettings(
            private_key_path=ssh["private_key_path"],
            username=ssh["username"],
            timeout_s=int(ssh["timeout_s"]),
            retry_count=int(ssh["retry_count"]),
            retry_delay_s=int(ssh["retry_delay_s"]),
            parallel_limit=int(ssh["parallel_limit"]),
        ),
        network=NetworkSettings(
            subnet=net["subnet"],
            scan_interval_s=int(net["scan_interval_s"]),
        ),
        server=ServerSettings(
            host=srv["host"],
            port=int(srv["port"]),
            log_level=srv["log_level"],
            workers=int(srv["workers"]),
        ),
    )


@functools.lru_cache(maxsize=1)
def get_settings(path: str = "config.yaml") -> Settings:
    return _load(path)


# Runtime SSH overrides — populated by PATCH /settings, take precedence over config.yaml.
_ssh_overrides: dict = {}


def get_ssh_overrides() -> dict:
    return _ssh_overrides


def apply_ssh_override(
    key_path: str | None = None,
    username: str | None = None,
    timeout_s: int | None = None,
) -> None:
    if key_path is not None:
        _ssh_overrides["private_key_path"] = key_path
    if username is not None:
        _ssh_overrides["username"] = username
    if timeout_s is not None:
        _ssh_overrides["timeout_s"] = timeout_s


def effective_ssh_settings() -> SSHSettings:
    """Returns SSH settings with any runtime overrides applied."""
    base = get_settings().ssh
    if not _ssh_overrides:
        return base
    import dataclasses
    return dataclasses.replace(base, **_ssh_overrides)
