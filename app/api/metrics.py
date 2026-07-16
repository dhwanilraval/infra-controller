"""Prometheus metrics endpoint.

Generates metrics in Prometheus exposition format (text/plain) without
requiring the prometheus_client library.  The /metrics route is
unauthenticated so that Prometheus can scrape it directly.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.machine import Machine, MachineEvent, Workflow
from app.models.provisioning import ProvisioningJob

router = APIRouter(tags=["metrics"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _fmt_label_val(v: object) -> str:
    """Escape a label value for Prometheus exposition format."""
    s = str(v) if v is not None else ""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(db: AsyncSession = Depends(get_db)):
    lines: list[str] = []

    # ------------------------------------------------------------------
    # ic_machines_total  (gauge, labeled by state/vendor/health/power)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_machines_total Total number of machines")
    lines.append("# TYPE ic_machines_total gauge")

    stmt = (
        select(
            Machine.state,
            Machine.vendor,
            Machine.health_status,
            Machine.power_state,
            func.count(),
        )
        .group_by(
            Machine.state,
            Machine.vendor,
            Machine.health_status,
            Machine.power_state,
        )
    )
    result = await db.execute(stmt)
    for state, vendor, health_status, power_state, count in result.all():
        labels = (
            f'state="{_fmt_label_val(state)}",'
            f'vendor="{_fmt_label_val(vendor)}",'
            f'health_status="{_fmt_label_val(health_status)}",'
            f'power_state="{_fmt_label_val(power_state)}"'
        )
        lines.append(f"ic_machines_total{{{labels}}} {count}")

    # ------------------------------------------------------------------
    # ic_workflows_total  (gauge, labeled by status/workflow_type)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_workflows_total Total number of workflows")
    lines.append("# TYPE ic_workflows_total gauge")

    stmt = (
        select(
            Workflow.status,
            Workflow.workflow_type,
            func.count(),
        )
        .group_by(Workflow.status, Workflow.workflow_type)
    )
    result = await db.execute(stmt)
    for status, workflow_type, count in result.all():
        labels = (
            f'status="{_fmt_label_val(status)}",'
            f'workflow_type="{_fmt_label_val(workflow_type)}"'
        )
        lines.append(f"ic_workflows_total{{{labels}}} {count}")

    # ------------------------------------------------------------------
    # ic_provisioning_jobs_total  (gauge, labeled by status)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_provisioning_jobs_total Total number of provisioning jobs")
    lines.append("# TYPE ic_provisioning_jobs_total gauge")

    stmt = (
        select(ProvisioningJob.status, func.count())
        .group_by(ProvisioningJob.status)
    )
    result = await db.execute(stmt)
    for status, count in result.all():
        lines.append(
            f'ic_provisioning_jobs_total{{status="{_fmt_label_val(status)}"}} {count}'
        )

    # ------------------------------------------------------------------
    # ic_machines_gpu_total  (gauge, simple count)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_machines_gpu_total Machines with GPUs")
    lines.append("# TYPE ic_machines_gpu_total gauge")

    stmt = select(func.count()).select_from(Machine).where(Machine.gpu_count > 0)
    result = await db.execute(stmt)
    gpu_total = result.scalar() or 0
    lines.append(f"ic_machines_gpu_total {gpu_total}")

    # ------------------------------------------------------------------
    # ic_machines_tpm_present  (gauge, simple count)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_machines_tpm_present Machines with TPM present")
    lines.append("# TYPE ic_machines_tpm_present gauge")

    stmt = (
        select(func.count())
        .select_from(Machine)
        .where(Machine.tpm_present.is_(True))
    )
    result = await db.execute(stmt)
    tpm_total = result.scalar() or 0
    lines.append(f"ic_machines_tpm_present {tpm_total}")

    # ------------------------------------------------------------------
    # ic_events_total  (counter-style gauge, total event count)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_events_total Total number of machine events")
    lines.append("# TYPE ic_events_total gauge")

    stmt = select(func.count()).select_from(MachineEvent)
    result = await db.execute(stmt)
    events_total = result.scalar() or 0
    lines.append(f"ic_events_total {events_total}")

    # ------------------------------------------------------------------
    # ic_discovery_last_run_timestamp  (gauge, placeholder)
    # ------------------------------------------------------------------
    lines.append(
        "# HELP ic_discovery_last_run_timestamp "
        "Unix timestamp of the last discovery run"
    )
    lines.append("# TYPE ic_discovery_last_run_timestamp gauge")
    lines.append("ic_discovery_last_run_timestamp 0")

    # ------------------------------------------------------------------
    # ic_api_info  (info-style gauge)
    # ------------------------------------------------------------------
    lines.append("# HELP ic_api_info Infra Controller API metadata")
    lines.append("# TYPE ic_api_info gauge")
    lines.append('ic_api_info{version="0.1.0"} 1')

    # Prometheus expects a trailing newline.
    lines.append("")
    return PlainTextResponse(
        content="\n".join(lines),
        media_type=CONTENT_TYPE,
    )
