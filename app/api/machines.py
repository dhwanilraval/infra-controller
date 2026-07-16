from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, Role, get_current_user, require_admin, require_operator, require_viewer
from app.database import get_db
from app.engine.workflows import workflow_engine
from app.models.machine import Machine, MachineState, Workflow
from app.redfish.client import RedfishClient, RedfishError
from app.schemas.machine import (
    BiosUpdate,
    FirmwareUpdate,
    MachineCreate,
    MachineResponse,
    MachineSummary,
    MachineUpdate,
    PowerAction,
    StorageVolumeCreate,
    WorkflowCreate,
    WorkflowResponse,
)

router = APIRouter(
    prefix="/api/v1/machines",
    tags=["machines"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[MachineSummary])
async def list_machines(
    state: str | None = None,
    vendor: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Machine)
    if state:
        query = query.where(Machine.state == state)
    if vendor:
        query = query.where(Machine.vendor.ilike(f"%{vendor}%"))
    result = await db.execute(query.order_by(Machine.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=MachineResponse, status_code=201)
async def register_machine(
    data: MachineCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Machine).where(Machine.bmc_ip == data.bmc_ip)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Machine with BMC IP {data.bmc_ip} already exists")

    machine = Machine(**data.model_dump())
    db.add(machine)
    await db.flush()

    wf = Workflow(
        machine_id=machine.id,
        workflow_type="enroll",
        status="pending",
        steps_total=["connect_bmc", "collect_inventory", "complete"],
    )
    db.add(wf)
    await db.commit()
    await db.refresh(machine)

    background.add_task(workflow_engine.start_workflow, machine.id, wf.id, "enroll", {})
    return machine


@router.get("/{machine_id}", response_model=MachineResponse)
async def get_machine(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    return machine


@router.patch("/{machine_id}", response_model=MachineResponse)
async def update_machine(
    machine_id: int,
    data: MachineUpdate,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(machine, key, value)
    machine.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(machine)
    return machine


@router.delete("/{machine_id}", status_code=204)
async def delete_machine(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    if machine.state not in (MachineState.DECOMMISSIONED, MachineState.DISCOVERED):
        raise HTTPException(
            400, "Machine must be decommissioned or in discovered state to delete"
        )
    await db.delete(machine)
    await db.commit()


# ── Power Management ──


@router.post("/{machine_id}/power")
async def power_action(
    machine_id: int,
    action: PowerAction,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            result = await client.set_power_state(action.action)
            machine.power_state = (
                "On" if action.action in ("on", "restart", "force_restart") else "Off"
            )
            machine.last_seen = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "ok", "action": action.action, "result": result}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.get("/{machine_id}/power")
async def get_power(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            state = await client.get_power_state()
            machine.power_state = state
            machine.last_seen = datetime.now(timezone.utc)
            await db.commit()
            return {"power_state": state}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── BIOS ──


@router.get("/{machine_id}/bios")
async def get_bios(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            attrs = await client.get_bios_attributes()
            return {"attributes": attrs}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.patch("/{machine_id}/bios")
async def update_bios(
    machine_id: int,
    data: BiosUpdate,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            result = await client.set_bios_attributes(data.attributes)
            return {"status": "ok", "result": result}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Boot ──


@router.get("/{machine_id}/boot")
async def get_boot(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            return await client.get_boot_order()
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.patch("/{machine_id}/boot")
async def set_boot(
    machine_id: int,
    target: str = "Pxe",
    mode: str = "UEFI",
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            result = await client.set_boot_override(target, mode)
            return {"status": "ok", "result": result}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Storage ──


@router.get("/{machine_id}/storage")
async def get_storage(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            controllers = await client.get_storage_controllers()
            drives = await client.get_drives()
            return {"controllers": controllers, "drives": drives}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Firmware ──


@router.get("/{machine_id}/firmware")
async def get_firmware(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            inventory = await client.get_firmware_inventory()
            return {"firmware": inventory}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.post("/{machine_id}/firmware/update")
async def update_firmware(
    machine_id: int,
    data: FirmwareUpdate,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            result = await client.update_firmware(data.image_uri, data.targets)
            return {"status": "ok", "result": result}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Health / Sensors ──


@router.get("/{machine_id}/health")
async def get_health(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            system = await client.get_system()
            chassis_list = await client.get_chassis()
            thermal = {}
            power_data = {}
            if chassis_list:
                cid = chassis_list[0].get("Id", "1")
                try:
                    thermal = await client.get_thermal(cid)
                except Exception:
                    pass
                try:
                    power_data = await client.get_power(cid)
                except Exception:
                    pass

            machine.health_status = system.get("Status", {}).get("Health")
            machine.power_state = system.get("PowerState")
            machine.last_seen = datetime.now(timezone.utc)
            await db.commit()

            return {
                "system_health": system.get("Status"),
                "power_state": system.get("PowerState"),
                "temperatures": thermal.get("Temperatures", []),
                "fans": thermal.get("Fans", []),
                "power_supplies": power_data.get("PowerSupplies", []),
                "power_consumed_watts": power_data.get("PowerControl", [{}])[0].get(
                    "PowerConsumedWatts"
                )
                if power_data.get("PowerControl")
                else None,
            }
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Logs ──


@router.get("/{machine_id}/logs")
async def get_logs(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            logs = await client.get_system_logs()
            return {"logs": logs}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Secure Boot ──


@router.get("/{machine_id}/secure-boot")
async def get_secure_boot(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            return await client.get_secure_boot()
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.patch("/{machine_id}/secure-boot")
async def set_secure_boot(
    machine_id: int,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            result = await client.set_secure_boot(enabled)
            return {"status": "ok", "result": result}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Virtual Media ──


@router.get("/{machine_id}/virtual-media")
async def get_virtual_media(machine_id: int, db: AsyncSession = Depends(get_db)):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            media = await client.get_virtual_media()
            return {"virtual_media": media}
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Raw Redfish Access ──


@router.get("/{machine_id}/redfish/{path:path}")
async def raw_redfish_get(
    machine_id: int,
    path: str,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            return await client.raw_get(f"/redfish/v1/{path}")
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


# ── Workflows ──


@router.post("/{machine_id}/workflows", response_model=WorkflowResponse)
async def create_workflow(
    machine_id: int,
    data: WorkflowCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    valid_types = ["enroll", "provision", "decommission", "health_check", "custom"]
    if data.workflow_type not in valid_types:
        raise HTTPException(400, f"Invalid workflow type. Must be one of: {valid_types}")

    wf = Workflow(
        machine_id=machine_id,
        workflow_type=data.workflow_type,
        status="pending",
        params=data.params,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)

    background.add_task(
        workflow_engine.start_workflow,
        machine_id,
        wf.id,
        data.workflow_type,
        data.params or {},
    )
    return wf


@router.get("/{machine_id}/workflows", response_model=list[WorkflowResponse])
async def list_workflows(machine_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Workflow)
        .where(Workflow.machine_id == machine_id)
        .order_by(Workflow.started_at.desc())
    )
    return result.scalars().all()


@router.post("/{machine_id}/workflows/{workflow_id}/resume", response_model=WorkflowResponse)
async def resume_workflow(
    machine_id: int,
    workflow_id: int,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Resume a failed workflow from its last checkpoint."""
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if wf.machine_id != machine_id:
        raise HTTPException(400, "Workflow does not belong to this machine")
    if wf.status != "failed":
        raise HTTPException(400, f"Cannot resume workflow in '{wf.status}' state — only 'failed' workflows can be resumed")
    if wf.retry_count >= wf.max_retries:
        raise HTTPException(400, f"Workflow exceeded max retries ({wf.max_retries})")

    background.add_task(workflow_engine.resume_workflow, workflow_id)
    await db.refresh(wf)
    return wf


@router.get("/{machine_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    machine_id: int,
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
):
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if wf.machine_id != machine_id:
        raise HTTPException(400, "Workflow does not belong to this machine")
    return wf
