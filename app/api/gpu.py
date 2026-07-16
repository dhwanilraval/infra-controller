"""GPU discovery, inventory, and health endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.machine import Machine
from app.redfish.client import RedfishClient, RedfishError

router = APIRouter(
    prefix="/api/v1/machines",
    tags=["gpu"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/{machine_id}/gpus")
async def get_gpus(machine_id: int, db: AsyncSession = Depends(get_db)):
    """Discover all GPUs in a machine via Redfish PCIe device enumeration."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            gpus = await client.get_gpus()
            machine.gpu_info = gpus
            machine.gpu_count = len(gpus)
            await db.commit()
            return {
                "gpu_count": len(gpus),
                "gpus": gpus,
            }
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.get("/{machine_id}/gpus/health")
async def get_gpu_health(machine_id: int, db: AsyncSession = Depends(get_db)):
    """Read GPU temperatures and health status from BMC sensors."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            gpus = await client.get_gpus()
            chassis = await client.get_chassis()
            gpu_temps = []
            if chassis:
                chassis_id = chassis[0].get("Id", "1")
                gpu_temps = await client.get_gpu_thermal(chassis_id)

            gpu_health = []
            for gpu in gpus:
                entry = {
                    "id": gpu.get("id"),
                    "name": gpu.get("name"),
                    "manufacturer": gpu.get("manufacturer"),
                    "status": gpu.get("status"),
                    "firmware_version": gpu.get("firmware_version"),
                    "serial_number": gpu.get("serial_number"),
                }
                matching_temp = next(
                    (
                        t
                        for t in gpu_temps
                        if gpu.get("id", "").lower() in t.get("name", "").lower()
                        or gpu.get("name", "").split()[0].lower()
                        in t.get("name", "").lower()
                    ),
                    None,
                )
                if matching_temp:
                    entry["temperature_celsius"] = matching_temp.get(
                        "reading_celsius"
                    )
                    entry["temp_threshold_critical"] = matching_temp.get(
                        "upper_threshold"
                    )
                gpu_health.append(entry)

            return {
                "gpu_count": len(gpus),
                "gpus": gpu_health,
                "gpu_temperatures": gpu_temps,
            }
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.get("/{machine_id}/pcie")
async def get_pcie_devices(machine_id: int, db: AsyncSession = Depends(get_db)):
    """List all PCIe devices — GPUs, NICs, RAID controllers, NVMe drives, etc."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
    try:
        async with client.session():
            devices = await client.get_pcie_devices()
            return {
                "pcie_device_count": len(devices),
                "devices": [
                    {
                        "id": d.get("Id"),
                        "name": d.get("Name"),
                        "manufacturer": d.get("Manufacturer"),
                        "model": d.get("Model"),
                        "device_class": d.get("DeviceClass"),
                        "serial_number": d.get("SerialNumber"),
                        "firmware_version": d.get("FirmwareVersion"),
                        "status": d.get("Status", {}).get("Health"),
                    }
                    for d in devices
                ],
            }
    except RedfishError as e:
        raise HTTPException(502, f"BMC error: {e.message}")


@router.get("/gpu-summary")
async def gpu_fleet_summary(db: AsyncSession = Depends(get_db)):
    """Fleet-wide GPU summary — how many GPUs across all machines."""
    result = await db.execute(
        select(Machine).where(Machine.gpu_count > 0)
    )
    gpu_machines = result.scalars().all()

    total_gpus = 0
    by_model = {}
    by_vendor = {}
    machines_with_gpus = []

    for m in gpu_machines:
        total_gpus += m.gpu_count or 0
        machines_with_gpus.append(
            {
                "id": m.id,
                "name": m.name,
                "gpu_count": m.gpu_count,
                "state": m.state.value if hasattr(m.state, "value") else m.state,
            }
        )
        for gpu in m.gpu_info or []:
            model = gpu.get("model") or gpu.get("name") or "Unknown"
            vendor = gpu.get("manufacturer") or "Unknown"
            by_model[model] = by_model.get(model, 0) + 1
            by_vendor[vendor] = by_vendor.get(vendor, 0) + 1

    return {
        "total_gpu_machines": len(gpu_machines),
        "total_gpus": total_gpus,
        "by_model": by_model,
        "by_vendor": by_vendor,
        "machines": machines_with_gpus,
    }
