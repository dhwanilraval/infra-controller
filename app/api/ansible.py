"""Optional Ansible bridge — only loaded when IC_ANSIBLE_ENABLED=true."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.engine.ansible_runner import PlaybookError, list_available_playbooks, run_playbook
from app.models.machine import Machine

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/ansible",
    tags=["ansible"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/{machine_id}/run")
async def run_ansible_playbook(
    machine_id: int,
    playbook: str,
    extra_vars: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    try:
        result = await run_playbook(
            playbook=playbook,
            extra_vars={
                "bmc_ip": machine.bmc_ip,
                "bmc_user": machine.bmc_username,
                "bmc_pass": machine.bmc_password,
                **(extra_vars or {}),
            },
            inventory_host=machine.bmc_ip,
        )
        return result
    except PlaybookError as e:
        raise HTTPException(500, f"Playbook failed: {e.stderr}")


@router.get("/playbooks")
async def list_playbooks():
    return {"playbooks": list_available_playbooks()}
