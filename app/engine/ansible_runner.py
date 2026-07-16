"""Ansible playbook runner — can be called standalone or as a workflow step."""

import asyncio
import json
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)


class PlaybookError(Exception):
    def __init__(self, playbook: str, stderr: str, returncode: int):
        self.playbook = playbook
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"Playbook '{playbook}' failed (rc={returncode}): {stderr}")


async def run_playbook(
    playbook: str,
    extra_vars: dict,
    inventory_host: str,
    timeout: int = 300,
) -> dict:
    playbook_path = os.path.join(settings.ansible_playbook_dir, playbook)
    if not playbook.endswith((".yml", ".yaml")):
        playbook_path += ".yml"

    if not os.path.isfile(playbook_path):
        raise PlaybookError(playbook, f"Playbook not found: {playbook_path}", 1)

    cmd = [
        "ansible-playbook",
        playbook_path,
        "-i", f"{inventory_host},",
        "-e", json.dumps(extra_vars),
        "--connection", "local",
    ]

    logger.info(f"Running playbook: {playbook} against {inventory_host}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise PlaybookError(playbook, f"Timed out after {timeout}s", -1)

    result = {
        "playbook": playbook,
        "returncode": proc.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
    }

    if proc.returncode != 0:
        raise PlaybookError(playbook, result["stderr"], proc.returncode)

    logger.info(f"Playbook {playbook} completed successfully")
    return result


def list_available_playbooks() -> list[dict]:
    playbook_dir = settings.ansible_playbook_dir
    if not os.path.isdir(playbook_dir):
        return []
    playbooks = []
    for f in sorted(os.listdir(playbook_dir)):
        if f.endswith((".yml", ".yaml")):
            playbooks.append({
                "name": f,
                "path": os.path.join(playbook_dir, f),
            })
    return playbooks
