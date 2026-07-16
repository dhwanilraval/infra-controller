"""TPM (Trusted Platform Module) inventory and status endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.machine import Machine
from app.redfish.client import RedfishClient, RedfishError

router = APIRouter(
    prefix="/api/v1/machines",
    tags=["tpm"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/{machine_id}/tpm")
async def get_tpm_status(machine_id: int, db: AsyncSession = Depends(get_db)):
    """Read TPM presence, version, and BIOS-level TPM policy from the BMC."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            modules = await client.get_trusted_modules()
            tpm_policy = await client.get_tpm_policy()

            secure_boot = {}
            try:
                secure_boot = await client.get_secure_boot()
            except RedfishError:
                pass

            tpm_present = len(modules) > 0 and any(
                m.get("status") == "Enabled" for m in modules
            )

            machine.tpm_info = {
                "modules": modules,
                "bios_policy": tpm_policy,
            }
            machine.tpm_present = tpm_present
            await db.commit()

            return {
                "tpm_present": tpm_present,
                "modules": modules,
                "bios_tpm_policy": tpm_policy,
                "secure_boot": {
                    "enabled": secure_boot.get("SecureBootEnable"),
                    "mode": secure_boot.get("SecureBootMode"),
                    "current_boot": secure_boot.get("SecureBootCurrentBoot"),
                },
            }
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.get("/tpm-summary")
async def tpm_fleet_summary(db: AsyncSession = Depends(get_db)):
    """Fleet-wide TPM summary — how many machines have TPM enabled."""
    result = await db.execute(select(Machine))
    all_machines = result.scalars().all()

    tpm_enabled = []
    tpm_disabled = []
    tpm_unknown = []

    for m in all_machines:
        entry = {
            "id": m.id,
            "name": m.name,
            "state": m.state.value if hasattr(m.state, "value") else m.state,
        }
        if m.tpm_present is True:
            tpm_enabled.append(entry)
        elif m.tpm_present is False and m.tpm_info is not None:
            tpm_disabled.append(entry)
        else:
            tpm_unknown.append(entry)

    return {
        "total_machines": len(all_machines),
        "tpm_enabled": len(tpm_enabled),
        "tpm_disabled": len(tpm_disabled),
        "tpm_unknown": len(tpm_unknown),
        "machines_with_tpm": tpm_enabled,
        "machines_without_tpm": tpm_disabled,
        "machines_not_scanned": tpm_unknown,
    }
