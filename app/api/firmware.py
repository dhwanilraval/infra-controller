import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.machine import Machine, MachineState
from app.models.firmware import FirmwareBaseline, ComplianceReport, ComplianceStatus
from app.schemas.firmware import (
    FirmwareBaselineCreate,
    FirmwareBaselineUpdate,
    FirmwareBaselineResponse,
    ComplianceReportResponse,
    FleetComplianceSummary,
)
from app.redfish.client import RedfishClient

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["firmware-compliance"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Baseline CRUD
# ---------------------------------------------------------------------------

@router.get("/firmware-baselines", response_model=list[FirmwareBaselineResponse])
async def list_baselines(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FirmwareBaseline).order_by(FirmwareBaseline.id))
    return result.scalars().all()


@router.post("/firmware-baselines", response_model=FirmwareBaselineResponse, status_code=201)
async def create_baseline(
    payload: FirmwareBaselineCreate,
    db: AsyncSession = Depends(get_db),
):
    baseline = FirmwareBaseline(**payload.model_dump())
    db.add(baseline)
    await db.commit()
    await db.refresh(baseline)
    return baseline


@router.get("/firmware-baselines/{baseline_id}", response_model=FirmwareBaselineResponse)
async def get_baseline(baseline_id: int, db: AsyncSession = Depends(get_db)):
    baseline = await db.get(FirmwareBaseline, baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return baseline


@router.patch("/firmware-baselines/{baseline_id}", response_model=FirmwareBaselineResponse)
async def update_baseline(
    baseline_id: int,
    payload: FirmwareBaselineUpdate,
    db: AsyncSession = Depends(get_db),
):
    baseline = await db.get(FirmwareBaseline, baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(baseline, field, value)
    baseline.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(baseline)
    return baseline


@router.delete("/firmware-baselines/{baseline_id}", status_code=204)
async def delete_baseline(baseline_id: int, db: AsyncSession = Depends(get_db)):
    baseline = await db.get(FirmwareBaseline, baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")
    await db.delete(baseline)
    await db.commit()


# ---------------------------------------------------------------------------
# Compliance check helpers
# ---------------------------------------------------------------------------

async def _check_machine_compliance(
    machine: Machine,
    baseline: FirmwareBaseline,
    db: AsyncSession,
) -> ComplianceReport:
    findings: list[dict] = []
    all_compliant = True

    # Check BIOS version
    expected_bios = baseline.rules.get("bios")
    if expected_bios:
        actual = machine.bios_version
        compliant = actual == expected_bios if actual else False
        findings.append({
            "component": "BIOS",
            "expected": expected_bios,
            "actual": actual,
            "compliant": compliant,
        })
        if not compliant:
            all_compliant = False

    # Check BMC firmware
    expected_bmc = baseline.rules.get("bmc")
    if expected_bmc:
        actual = machine.bmc_firmware
        compliant = actual == expected_bmc if actual else False
        findings.append({
            "component": "BMC",
            "expected": expected_bmc,
            "actual": actual,
            "compliant": compliant,
        })
        if not compliant:
            all_compliant = False

    # Check component firmware via Redfish
    components = baseline.rules.get("components", {})
    if components:
        try:
            client = RedfishClient(machine.bmc_ip, machine.bmc_username, machine.bmc_password)
            async with client.session():
                fw_inventory = await client.get_firmware_inventory()
                for comp_name, expected_ver in components.items():
                    actual_ver = None
                    for fw in fw_inventory:
                        if comp_name.lower() in (fw.get("Name", "") or "").lower():
                            actual_ver = fw.get("Version")
                            break
                    compliant = actual_ver == expected_ver if actual_ver else False
                    findings.append({
                        "component": comp_name,
                        "expected": expected_ver,
                        "actual": actual_ver,
                        "compliant": compliant,
                    })
                    if not compliant:
                        all_compliant = False
        except Exception:
            findings.append({
                "component": "Firmware Inventory",
                "expected": "accessible",
                "actual": "error",
                "compliant": False,
            })
            all_compliant = False

    status = ComplianceStatus.COMPLIANT if all_compliant else ComplianceStatus.NON_COMPLIANT

    report = ComplianceReport(
        machine_id=machine.id,
        baseline_id=baseline.id,
        status=status,
        findings=findings,
    )
    db.add(report)
    return report


async def _find_matching_baselines(
    machine: Machine,
    db: AsyncSession,
) -> list[FirmwareBaseline]:
    """Return active baselines whose vendor/model filters match the machine."""
    result = await db.execute(
        select(FirmwareBaseline).where(FirmwareBaseline.is_active == True)  # noqa: E712
    )
    baselines = result.scalars().all()
    matching = []
    for bl in baselines:
        if bl.vendor_filter and machine.vendor and bl.vendor_filter.lower() != machine.vendor.lower():
            continue
        if bl.model_filter and machine.model and bl.model_filter.lower() != machine.model.lower():
            continue
        matching.append(bl)
    return matching


# ---------------------------------------------------------------------------
# Compliance endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/machines/{machine_id}/compliance-check",
    response_model=list[ComplianceReportResponse],
)
async def run_compliance_check(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    baselines = await _find_matching_baselines(machine, db)
    if not baselines:
        raise HTTPException(status_code=404, detail="No active baselines match this machine")

    reports: list[ComplianceReport] = []
    for baseline in baselines:
        report = await _check_machine_compliance(machine, baseline, db)
        reports.append(report)

    await db.commit()
    for r in reports:
        await db.refresh(r)
    return reports


@router.get(
    "/machines/{machine_id}/compliance-reports",
    response_model=list[ComplianceReportResponse],
)
async def list_compliance_reports(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    result = await db.execute(
        select(ComplianceReport)
        .where(ComplianceReport.machine_id == machine_id)
        .order_by(ComplianceReport.checked_at.desc())
    )
    return result.scalars().all()


@router.get("/compliance-summary", response_model=FleetComplianceSummary)
async def get_compliance_summary(db: AsyncSession = Depends(get_db)):
    # Get the latest report per machine (using subquery for max checked_at)
    latest_subq = (
        select(
            ComplianceReport.machine_id,
            func.max(ComplianceReport.checked_at).label("latest"),
        )
        .group_by(ComplianceReport.machine_id)
        .subquery()
    )

    result = await db.execute(
        select(ComplianceReport).join(
            latest_subq,
            (ComplianceReport.machine_id == latest_subq.c.machine_id)
            & (ComplianceReport.checked_at == latest_subq.c.latest),
        )
    )
    latest_reports = result.scalars().all()

    # Aggregate counts
    total = len(latest_reports)
    compliant = sum(1 for r in latest_reports if r.status == ComplianceStatus.COMPLIANT)
    non_compliant = sum(1 for r in latest_reports if r.status == ComplianceStatus.NON_COMPLIANT)
    unknown = sum(1 for r in latest_reports if r.status == ComplianceStatus.UNKNOWN)
    error = sum(1 for r in latest_reports if r.status == ComplianceStatus.ERROR)
    compliance_rate = (compliant / total * 100) if total > 0 else 0.0

    # Group by baseline
    by_baseline: dict[str, dict] = {}
    for r in latest_reports:
        baseline = await db.get(FirmwareBaseline, r.baseline_id)
        bl_name = baseline.name if baseline else f"baseline-{r.baseline_id}"
        if bl_name not in by_baseline:
            by_baseline[bl_name] = {"compliant": 0, "non_compliant": 0, "unknown": 0, "error": 0, "total": 0}
        by_baseline[bl_name]["total"] += 1
        by_baseline[bl_name][r.status.value] = by_baseline[bl_name].get(r.status.value, 0) + 1

    return FleetComplianceSummary(
        total_machines=total,
        compliant=compliant,
        non_compliant=non_compliant,
        unknown=unknown,
        error=error,
        compliance_rate=round(compliance_rate, 2),
        by_baseline=by_baseline,
    )


async def _run_compliance_check_all(db: AsyncSession):
    """Background task: check compliance for all enrolled/ready machines."""
    result = await db.execute(
        select(Machine).where(Machine.state.in_([MachineState.ENROLLED, MachineState.READY]))
    )
    machines = result.scalars().all()

    for machine in machines:
        baselines = await _find_matching_baselines(machine, db)
        for baseline in baselines:
            try:
                await _check_machine_compliance(machine, baseline, db)
            except Exception:
                logger.exception(
                    "Compliance check failed for machine %s baseline %s",
                    machine.id,
                    baseline.id,
                )
    await db.commit()


@router.post("/compliance-check-all", status_code=202)
async def trigger_compliance_check_all(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Create a fresh session for the background task
    from app.database import async_session

    async def _background_job():
        async with async_session() as session:
            await _run_compliance_check_all(session)

    background_tasks.add_task(_background_job)
    return {"detail": "Compliance check for all machines queued"}
