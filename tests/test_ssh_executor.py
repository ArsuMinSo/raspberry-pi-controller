import socket
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from backend.config import SSHSettings
from backend.services.ssh_executor import SSHResult, execute, execute_many

SETTINGS = SSHSettings(
    private_key_path="/fake/key",
    username="pi",
    timeout_s=5,
    retry_count=2,
    retry_delay_s=0,
    parallel_limit=1,
)


def _make_channel(exit_code: int, stdout: bytes = b"ok", stderr: bytes = b""):
    channel = MagicMock()
    channel.recv_exit_status.return_value = exit_code
    stdout_fh = MagicMock()
    stdout_fh.read.return_value = stdout
    stdout_fh.channel = channel
    stderr_fh = MagicMock()
    stderr_fh.read.return_value = stderr
    return stdout_fh, stderr_fh


@patch("backend.services.ssh_executor.paramiko.RSAKey.from_private_key_file")
@patch("backend.services.ssh_executor.paramiko.SSHClient")
def test_execute_success(mock_client_cls, mock_key):
    client = MagicMock()
    mock_client_cls.return_value = client
    stdout_fh, stderr_fh = _make_channel(0, b"hello", b"")
    client.exec_command.return_value = (MagicMock(), stdout_fh, stderr_fh)

    result = execute("10.10.20.1", "01-001", "echo hello", SETTINGS)

    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.error is None
    assert result.retry_count == 0


@patch("backend.services.ssh_executor.paramiko.RSAKey.from_private_key_file")
@patch("backend.services.ssh_executor.paramiko.SSHClient")
def test_execute_nonzero_exit_no_retry(mock_client_cls, mock_key):
    client = MagicMock()
    mock_client_cls.return_value = client
    stdout_fh, stderr_fh = _make_channel(1, b"", b"error")
    client.exec_command.return_value = (MagicMock(), stdout_fh, stderr_fh)

    result = execute("10.10.20.1", "01-001", "false", SETTINGS)

    assert result.exit_code == 1
    assert result.retry_count == 0


@patch("backend.services.ssh_executor.time.sleep")
@patch("backend.services.ssh_executor.paramiko.RSAKey.from_private_key_file")
@patch("backend.services.ssh_executor.paramiko.SSHClient")
def test_execute_timeout_retries(mock_client_cls, mock_key, mock_sleep):
    client = MagicMock()
    mock_client_cls.return_value = client
    client.connect.side_effect = socket.timeout("timed out")

    result = execute("10.10.20.1", "01-001", "echo hi", SETTINGS)

    assert result.exit_code is None
    assert result.error is not None
    assert result.retry_count == SETTINGS.retry_count + 1
    assert mock_sleep.call_count == SETTINGS.retry_count


@patch("backend.services.ssh_executor.paramiko.RSAKey.from_private_key_file")
@patch("backend.services.ssh_executor.paramiko.SSHClient")
def test_execute_auth_fail_no_retry(mock_client_cls, mock_key):
    client = MagicMock()
    mock_client_cls.return_value = client
    client.connect.side_effect = paramiko.AuthenticationException("bad key")

    result = execute("10.10.20.1", "01-001", "echo hi", SETTINGS)

    assert result.exit_code is None
    assert "Auth failed" in result.error
    assert result.retry_count == 0


@patch("backend.services.ssh_executor.paramiko.RSAKey.from_private_key_file")
@patch("backend.services.ssh_executor.paramiko.SSHClient")
def test_execute_many_serial_order(mock_client_cls, mock_key):
    call_order = []
    client = MagicMock()
    mock_client_cls.return_value = client

    def connect_side_effect(ip, **kwargs):
        call_order.append(ip)

    client.connect.side_effect = connect_side_effect
    stdout_fh, stderr_fh = _make_channel(0)
    client.exec_command.return_value = (MagicMock(), stdout_fh, stderr_fh)

    targets = [("10.10.20.1", "01-001"), ("10.10.20.2", "01-002"), ("10.10.20.3", "01-003")]
    results = execute_many(targets, "uptime", SETTINGS)

    assert [r.position for r in results] == ["01-001", "01-002", "01-003"]
    assert call_order == ["10.10.20.1", "10.10.20.2", "10.10.20.3"]
