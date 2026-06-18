import os
import socket

import paramiko
from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import (
    apply_network_override,
    apply_ssh_override,
    effective_network_settings,
    effective_ssh_settings,
    persist_network_settings,
    persist_ssh_settings,
)
from backend.utils.helpers import load_private_key

router = APIRouter()


class SettingsPatch(BaseModel):
    ssh_key_path: str | None = None
    username: str | None = None
    timeout_s: int | None = None
    subnet: str | None = None
    probe_ssh: bool | None = None
    probe_timeout_s: int | None = None


class SSHTestRequest(BaseModel):
    ip: str


def _ssh_view(ssh) -> dict:
    return {
        "private_key_path": ssh.private_key_path,
        "username": ssh.username,
        "timeout_s": ssh.timeout_s,
    }


def _net_view(net) -> dict:
    return {
        "subnet": net.subnet,
        "probe_ssh": net.probe_ssh,
        "probe_timeout_s": net.probe_timeout_s,
    }


@router.get("")
def get_settings_view():
    return {
        "ssh": _ssh_view(effective_ssh_settings()),
        "network": _net_view(effective_network_settings()),
    }


@router.patch("")
def patch_settings(body: SettingsPatch):
    apply_ssh_override(
        key_path=body.ssh_key_path,
        username=body.username,
        timeout_s=body.timeout_s,
    )
    apply_network_override(
        subnet=body.subnet,
        probe_ssh=body.probe_ssh,
        probe_timeout_s=body.probe_timeout_s,
    )
    persist_ssh_settings()
    persist_network_settings()
    return {
        "ssh": _ssh_view(effective_ssh_settings()),
        "network": _net_view(effective_network_settings()),
    }


@router.post("/test")
def test_ssh(body: SSHTestRequest):
    ssh = effective_ssh_settings()
    result: dict = {
        "ip": body.ip,
        "success": False,
        "settings_used": _ssh_view(ssh),
        "error": None,
        "error_type": None,
        "stdout": None,
    }

    if not os.path.exists(ssh.private_key_path):
        result["error"] = f"Key file not found: {ssh.private_key_path}"
        result["error_type"] = "KeyFileNotFound"
        return result

    try:
        key = load_private_key(ssh.private_key_path)
    except Exception as e:
        result["error"] = str(e)
        result["error_type"] = "KeyLoadError"
        return result

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            body.ip,
            username=ssh.username,
            pkey=key,
            timeout=ssh.timeout_s,
            banner_timeout=ssh.timeout_s,
            auth_timeout=ssh.timeout_s,
        )
        _, out, err = client.exec_command("echo ok && hostname && whoami", timeout=10)
        stdout = out.read().decode(errors="replace").strip()
        stderr = err.read().decode(errors="replace").strip()
        result["success"] = True
        result["stdout"] = stdout + (f"\nstderr: {stderr}" if stderr else "")
    except paramiko.AuthenticationException as e:
        result["error"] = f"Authentication failed — wrong key or username? ({e})"
        result["error_type"] = "AuthenticationError"
    except paramiko.BadHostKeyException as e:
        result["error"] = f"Host key mismatch: {e}"
        result["error_type"] = "BadHostKey"
    except paramiko.SSHException as e:
        result["error"] = f"SSH protocol error: {e}"
        result["error_type"] = "SSHError"
    except socket.timeout:
        result["error"] = f"Connection timed out after {ssh.timeout_s}s — Pi unreachable or firewall?"
        result["error_type"] = "Timeout"
    except OSError as e:
        result["error"] = f"Network error: {e}"
        result["error_type"] = "NetworkError"
    finally:
        client.close()

    return result
