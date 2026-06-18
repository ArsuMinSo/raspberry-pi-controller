from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import apply_ssh_override, effective_ssh_settings

router = APIRouter()


class SettingsPatch(BaseModel):
    ssh_key_path: str | None = None


def _ssh_view(ssh) -> dict:
    return {
        "private_key_path": ssh.private_key_path,
        "username": ssh.username,
        "timeout_s": ssh.timeout_s,
    }


@router.get("")
def get_settings_view():
    return {"ssh": _ssh_view(effective_ssh_settings())}


@router.patch("")
def patch_settings(body: SettingsPatch):
    apply_ssh_override(key_path=body.ssh_key_path)
    return {"ssh": _ssh_view(effective_ssh_settings())}
