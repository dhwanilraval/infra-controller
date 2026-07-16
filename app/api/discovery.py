from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.engine.workflows import workflow_engine
from app.models.machine import Machine, Workflow
from app.redfish.discovery import discover_subnet
from app.schemas.machine import DiscoveryRequest, DiscoveryResult, MachineSummary

router = APIRouter(
    prefix="/api/v1/discovery",
    tags=["discovery"],
    dependencies=[Depends(get_current_user)],
)


@router.post("", response_model=DiscoveryResult)
async def discover(
    req: DiscoveryRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    found = await discover_subnet(
        subnet=req.subnet,
        username=req.bmc_username,
        password=req.bmc_password,
        port=req.port,
    )

    machines = []
    errors = []

    for host in found:
        ip = host["ip"]
        existing = await db.execute(select(Machine).where(Machine.bmc_ip == ip))
        if existing.scalar_one_or_none():
            errors.append({"ip": ip, "error": "Already registered"})
            continue

        service_root = host.get("service_root", {})
        vendor = service_root.get("Vendor", "Unknown")

        machine = Machine(
            name=f"server-{ip.replace('.', '-')}",
            bmc_ip=ip,
            bmc_username=req.bmc_username,
            bmc_password=req.bmc_password,
            vendor=vendor,
        )
        db.add(machine)
        await db.flush()

        wf = Workflow(
            machine_id=machine.id,
            workflow_type="enroll",
            status="pending",
            steps_total=["connect_bmc", "collect_inventory", "complete"],
        )
        db.add(wf)
        await db.flush()

        background.add_task(
            workflow_engine.start_workflow, machine.id, wf.id, "enroll", {}
        )
        machines.append(machine)

    await db.commit()

    return DiscoveryResult(
        discovered=len(machines),
        machines=[MachineSummary.model_validate(m) for m in machines],
        errors=errors,
    )
