import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import paramiko

from backend.config import SSHSettings
from backend.utils.helpers import load_private_key


@dataclass
class SSHResult:
    position: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None
    duration_ms: int
    retry_count: int


def execute(ip: str, position: str, command: str, settings: SSHSettings) -> SSHResult:
    key = load_private_key(settings.private_key_path)
    attempts = 0
    start = time.monotonic()

    while True:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip,
                username=settings.username,
                pkey=key,
                timeout=settings.timeout_s,
                banner_timeout=settings.timeout_s,
                auth_timeout=settings.timeout_s,
            )
            _, stdout_fh, stderr_fh = client.exec_command(
                command, timeout=settings.timeout_s
            )
            out = stdout_fh.read().decode(errors="replace")
            err = stderr_fh.read().decode(errors="replace")
            code = stdout_fh.channel.recv_exit_status()
            duration = int((time.monotonic() - start) * 1000)
            return SSHResult(
                position=position,
                exit_code=code,
                stdout=out,
                stderr=err,
                error=None,
                duration_ms=duration,
                retry_count=attempts,
            )
        except paramiko.AuthenticationException as e:
            duration = int((time.monotonic() - start) * 1000)
            return SSHResult(
                position=position,
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Auth failed: {e}",
                duration_ms=duration,
                retry_count=attempts,
            )
        except (socket.timeout, paramiko.SSHException, OSError) as e:
            attempts += 1
            if attempts > settings.retry_count:
                duration = int((time.monotonic() - start) * 1000)
                return SSHResult(
                    position=position,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=f"Connection failed after {attempts} attempt(s): {e}",
                    duration_ms=duration,
                    retry_count=attempts,
                )
            time.sleep(settings.retry_delay_s)
        finally:
            client.close()


def execute_many(
    targets: list[tuple[str, str]],
    command: str,
    settings: SSHSettings,
) -> list[SSHResult]:
    """targets: list of (ip, position). Parallel execution, order preserved."""
    if not targets:
        return []
    workers = min(settings.parallel_limit, len(targets))
    result_map: dict[str, SSHResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(execute, ip, pos, command, settings): pos
            for ip, pos in targets
        }
        for future in as_completed(futures):
            r = future.result()
            result_map[r.position] = r
    return [result_map[pos] for _, pos in targets]
