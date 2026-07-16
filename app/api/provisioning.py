"""Provisioning profiles, OS deployment trigger, callback webhook, and config file serving."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.engine.workflows import workflow_engine
from app.events.manager import event_manager
from app.models.machine import Machine, MachineState, Workflow
from app.models.provisioning import (
    OSFamily,
    ProvisioningJob,
    ProvisioningProfile,
    ProvisionMethod,
)
from app.provisioning.orchestrator import orchestrator
from app.schemas.provisioning import (
    CallbackPayload,
    ProvisioningJobResponse,
    ProvisioningProfileCreate,
    ProvisioningProfileResponse,
    ProvisioningProfileUpdate,
    ProvisionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["provisioning"])


# ── Provisioning Profiles CRUD ──


@router.get(
    "/provisioning-profiles",
    response_model=list[ProvisioningProfileResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProvisioningProfile).order_by(ProvisioningProfile.name)
    )
    return result.scalars().all()


@router.post(
    "/provisioning-profiles",
    response_model=ProvisioningProfileResponse,
    status_code=201,
    dependencies=[Depends(get_current_user)],
)
async def create_profile(
    data: ProvisioningProfileCreate, db: AsyncSession = Depends(get_db)
):
    profile = ProvisioningProfile(
        name=data.name,
        os_family=OSFamily(data.os_family),
        os_version=data.os_version,
        provision_method=ProvisionMethod(data.provision_method),
        network_config=data.network_config,
        disk_config=data.disk_config,
        packages=data.packages,
        users_config=data.users_config,
        post_scripts=data.post_scripts,
        cluster_config=data.cluster_config,
        satellite_hostgroup_id=data.satellite_hostgroup_id,
        satellite_content_view_id=data.satellite_content_view_id,
        satellite_activation_key=data.satellite_activation_key,
        mecm_task_sequence_id=data.mecm_task_sequence_id,
        mecm_collection_id=data.mecm_collection_id,
        vcenter_cluster_name=data.vcenter_cluster_name,
        vcenter_datastore=data.vcenter_datastore,
        config_template=data.config_template,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get(
    "/provisioning-profiles/{profile_id}",
    response_model=ProvisioningProfileResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    profile = await db.get(ProvisioningProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return profile


@router.patch(
    "/provisioning-profiles/{profile_id}",
    response_model=ProvisioningProfileResponse,
    dependencies=[Depends(get_current_user)],
)
async def update_profile(
    profile_id: int,
    data: ProvisioningProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    profile = await db.get(ProvisioningProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete(
    "/provisioning-profiles/{profile_id}",
    status_code=204,
    dependencies=[Depends(get_current_user)],
)
async def delete_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    profile = await db.get(ProvisioningProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    await db.delete(profile)
    await db.commit()


# ── Provision a Machine ──


@router.post(
    "/machines/{machine_id}/provision",
    response_model=ProvisioningJobResponse,
    dependencies=[Depends(get_current_user)],
)
async def provision_machine(
    machine_id: int,
    data: ProvisionRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start OS provisioning: hardware prep (our workflow) + OS install (external tool)."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")

    profile = await db.get(ProvisioningProfile, data.profile_id)
    if not profile:
        raise HTTPException(404, "Provisioning profile not found")

    if machine.state not in (MachineState.ENROLLED, MachineState.READY, MachineState.ERROR):
        raise HTTPException(
            400,
            f"Machine must be in enrolled, ready, or error state to provision (current: {machine.state.value})",
        )

    # Create provisioning job
    job = ProvisioningJob(
        machine_id=machine_id,
        profile_id=profile.id,
        hostname=data.hostname or machine.name,
        ip_address=data.ip_address,
        status="pending",
    )
    db.add(job)

    # Create the hardware prep workflow
    wf = Workflow(
        machine_id=machine_id,
        workflow_type="provision",
        status="pending",
        params={
            "profile_id": profile.id,
            "job_id": None,  # Updated after flush
            "os_name": f"{profile.os_family.value} {profile.os_version}",
            "bios_attributes": profile.disk_config.get("bios", {}) if profile.disk_config else {},
            "raid": profile.disk_config.get("raid") if profile.disk_config else None,
        },
    )
    db.add(wf)
    await db.flush()

    job.workflow_id = wf.id
    wf.params["job_id"] = job.id
    await db.commit()
    await db.refresh(job)

    # Start hardware prep workflow, then OS provisioning
    background.add_task(
        _run_full_provision, machine_id, wf.id, job.id, profile.id
    )

    return job


async def _run_full_provision(
    machine_id: int, workflow_id: int, job_id: int, profile_id: int
):
    """Background task: hardware prep workflow → external OS provisioning."""
    from app.database import async_session

    # Step 1: Run hardware prep workflow
    await workflow_engine.start_workflow(
        machine_id, workflow_id, "provision",
        {"os_name": "pending", "profile_id": profile_id},
    )

    # Wait for workflow to finish
    import asyncio
    for _ in range(120):
        async with async_session() as db:
            wf = await db.get(Workflow, workflow_id)
            if wf and wf.status in ("completed", "failed"):
                break
        await asyncio.sleep(5)

    # Step 2: Start OS provisioning via external tool
    async with async_session() as db:
        wf = await db.get(Workflow, workflow_id)
        if wf and wf.status == "failed":
            job = await db.get(ProvisioningJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = "Hardware prep workflow failed"
                await db.commit()
            return

        machine = await db.get(Machine, machine_id)
        profile = await db.get(ProvisioningProfile, profile_id)
        job = await db.get(ProvisioningJob, job_id)

        try:
            result = await orchestrator.start_provision(db, machine, profile, job)
            job.status = "os_deploying"
            await db.commit()

            await event_manager.broadcast({
                "type": "provision_started",
                "machine_id": machine_id,
                "job_id": job_id,
                "method": profile.provision_method.value,
                "result": result,
            })
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            await db.commit()


# ── Provisioning Jobs ──


@router.get(
    "/machines/{machine_id}/provision-jobs",
    response_model=list[ProvisioningJobResponse],
    dependencies=[Depends(get_current_user)],
)
async def list_provision_jobs(machine_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProvisioningJob)
        .where(ProvisioningJob.machine_id == machine_id)
        .order_by(ProvisioningJob.started_at.desc())
    )
    return result.scalars().all()


@router.get(
    "/machines/{machine_id}/provision-jobs/{job_id}/status",
    dependencies=[Depends(get_current_user)],
)
async def check_provision_status(
    machine_id: int, job_id: int, db: AsyncSession = Depends(get_db)
):
    """Poll external tool for provisioning completion status."""
    job = await db.get(ProvisioningJob, job_id)
    if not job or job.machine_id != machine_id:
        raise HTTPException(404, "Provisioning job not found")

    profile = await db.get(ProvisioningProfile, job.profile_id)
    status = await orchestrator.check_status(job, profile)
    return {"job_id": job_id, **status}


# ── Callback Webhook (no auth — installer calls this) ──


@router.post("/provision-callback")
async def provision_callback(
    payload: CallbackPayload, db: AsyncSession = Depends(get_db)
):
    """Webhook called by the OS installer when provisioning is complete.

    Matches by machine_id (if provided) or hostname lookup.
    """
    job = None

    if payload.machine_id:
        result = await db.execute(
            select(ProvisioningJob)
            .where(
                ProvisioningJob.machine_id == payload.machine_id,
                ProvisioningJob.status == "os_deploying",
            )
            .order_by(ProvisioningJob.started_at.desc())
            .limit(1)
        )
        job = result.scalar_one_or_none()

    if not job and payload.hostname:
        result = await db.execute(
            select(ProvisioningJob)
            .where(
                ProvisioningJob.hostname == payload.hostname,
                ProvisioningJob.status == "os_deploying",
            )
            .order_by(ProvisioningJob.started_at.desc())
            .limit(1)
        )
        job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(404, "No active provisioning job found for this host")

    job.callback_received = True
    job.callback_data = {
        "status": payload.status,
        "message": payload.message,
        "extra": payload.extra,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    if payload.status == "complete":
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        machine = await db.get(Machine, job.machine_id)
        if machine and machine.state == MachineState.PROVISIONING:
            machine.state = MachineState.READY
            machine.os_installed = f"provisioned ({job.hostname})"
            machine.last_seen = datetime.now(timezone.utc)
    elif payload.status == "failed":
        job.status = "failed"
        job.error_message = payload.message or "Installer reported failure"
        job.completed_at = datetime.now(timezone.utc)

    await db.commit()

    await event_manager.broadcast({
        "type": "provision_callback",
        "machine_id": job.machine_id,
        "job_id": job.id,
        "status": payload.status,
        "hostname": payload.hostname,
    })

    return {"status": "ok", "job_id": job.id, "machine_state": "READY" if payload.status == "complete" else job.status}


# ── Serve Ignition / Answer Files ──


@router.get("/provision-files/{machine_id}/{filename}")
async def serve_provision_file(machine_id: int, filename: str):
    """Serve generated config files (Ignition JSON, kickstart, etc.) to the installer."""
    filepath = os.path.join(settings.ignition_serve_dir, str(machine_id), filename)
    if not os.path.isfile(filepath):
        raise HTTPException(404, "Config file not found")

    with open(filepath) as f:
        content = f.read()

    content_type = "application/json" if filename.endswith(".ign") else "text/plain"
    return PlainTextResponse(content, media_type=content_type)


# ── Integration Status ──


@router.get(
    "/provisioning-integrations",
    dependencies=[Depends(get_current_user)],
)
async def get_integrations():
    """Show which OS provisioning integrations are enabled."""
    return {
        "satellite": {
            "enabled": settings.satellite_enabled,
            "url": settings.satellite_url if settings.satellite_enabled else None,
            "os_families": ["rhel", "ubuntu"],
        },
        "mecm": {
            "enabled": settings.mecm_enabled,
            "url": settings.mecm_url if settings.mecm_enabled else None,
            "os_families": ["windows"],
        },
        "vcenter": {
            "enabled": settings.vcenter_enabled,
            "url": settings.vcenter_url if settings.vcenter_enabled else None,
            "os_families": ["esxi"],
        },
        "ignition": {
            "enabled": True,
            "os_families": ["coreos", "flatcar"],
        },
    }
