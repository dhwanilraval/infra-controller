from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.machine import Machine, MachineEvent, Workflow
from app.schemas.machine import EventResponse, HealthSummary

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/summary", response_model=HealthSummary)
async def fleet_summary(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count(Machine.id)))

    state_rows = await db.execute(
        select(Machine.state, func.count()).group_by(Machine.state)
    )
    by_state = {row[0].value if hasattr(row[0], "value") else row[0]: row[1] for row in state_rows}

    health_rows = await db.execute(
        select(Machine.health_status, func.count()).group_by(Machine.health_status)
    )
    by_health = {(row[0] or "Unknown"): row[1] for row in health_rows}

    power_rows = await db.execute(
        select(Machine.power_state, func.count()).group_by(Machine.power_state)
    )
    by_power = {(row[0] or "Unknown"): row[1] for row in power_rows}

    vendor_rows = await db.execute(
        select(Machine.vendor, func.count()).group_by(Machine.vendor)
    )
    by_vendor = {(row[0] or "Unknown"): row[1] for row in vendor_rows}

    return HealthSummary(
        total_machines=total or 0,
        by_state=by_state,
        by_health=by_health,
        by_power=by_power,
        by_vendor=by_vendor,
    )


@router.get("/events", response_model=list[EventResponse])
async def recent_events(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MachineEvent)
        .order_by(MachineEvent.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/workflows")
async def active_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Workflow)
        .where(Workflow.status.in_(["pending", "running"]))
        .order_by(Workflow.started_at.desc())
    )
    workflows = result.scalars().all()
    return [
        {
            "id": wf.id,
            "machine_id": wf.machine_id,
            "type": wf.workflow_type,
            "status": wf.status,
            "current_step": wf.current_step,
            "started_at": wf.started_at.isoformat() if wf.started_at else None,
        }
        for wf in workflows
    ]
