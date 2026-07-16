"""IPMI fallback endpoints for legacy BMCs without Redfish support."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.ipmi.client import IPMIClient, IPMIError, check_ipmi_available
from app.models.machine import Machine
from app.schemas.machine import PowerAction

router = APIRouter(
    prefix="/api/v1/machines",
    tags=["ipmi"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/{machine_id}/ipmi/power")
async def ipmi_get_power(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        state = await client.get_power_state()
        return {"power_state": state, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.post("/{machine_id}/ipmi/power")
async def ipmi_set_power(
    machine_id: int,
    action: PowerAction,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        result = await client.set_power_state(action.action)
        return {**result, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.get("/{machine_id}/ipmi/sensors")
async def ipmi_get_sensors(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        sensors = await client.get_sensor_data()
        return {"sensor_count": len(sensors), "sensors": sensors, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.get("/{machine_id}/ipmi/inventory")
async def ipmi_get_inventory(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        inventory = await client.get_inventory()
        return {**inventory, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.get("/{machine_id}/ipmi/boot")
async def ipmi_get_boot(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        boot = await client.get_boot_device()
        return {**boot, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.get("/{machine_id}/ipmi/events")
async def ipmi_get_events(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = IPMIClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        events = await client.get_system_event_log()
        return {"event_count": len(events), "events": events, "protocol": "ipmi"}
    except IPMIError as e:
        raise HTTPException(502, f"IPMI error: {e.message}")


@router.get("/{machine_id}/ipmi/check")
async def ipmi_check_availability(machine_id: int, db: AsyncSession = Depends(get_db)):
    """Check if IPMI is reachable on this machine's BMC."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    available = await check_ipmi_available(
        machine.bmc_ip, machine.bmc_username, machine.bmc_password
    )
    return {"ipmi_available": available, "bmc_ip": machine.bmc_ip}
