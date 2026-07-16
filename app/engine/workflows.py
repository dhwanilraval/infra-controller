import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.engine.state_machine import validate_transition
from app.events.manager import event_manager
from app.models.machine import Machine, MachineEvent, MachineState, Workflow
from app.redfish.client import RedfishClient, build_inventory
from app.redfish.discovery import enroll_discovered_host

logger = logging.getLogger(__name__)

StepFn = Callable[..., Coroutine[Any, Any, dict]]


class WorkflowEngine:
    """Executes multi-step workflows against machines via Redfish and/or Ansible."""

    def __init__(self):
        self._running: dict[int, asyncio.Task] = {}

    async def _transition(
        self, db: AsyncSession, machine: Machine, new_state: MachineState
    ):
        old_state = machine.state
        validate_transition(old_state, new_state)
        machine.state = new_state
        machine.updated_at = datetime.now(timezone.utc)
        event = MachineEvent(
            machine_id=machine.id,
            event_type="state_change",
            previous_state=old_state.value,
            new_state=new_state.value,
        )
        db.add(event)
        await db.flush()
        await event_manager.broadcast(
            {
                "type": "state_change",
                "machine_id": machine.id,
                "from": old_state.value,
                "to": new_state.value,
            }
        )

    async def _update_workflow(
        self, db: AsyncSession, wf: Workflow, step: str, status: str = "running"
    ):
        wf.current_step = step
        wf.status = status
        wf.last_checkpoint = step
        if isinstance(wf.steps_completed, list):
            wf.steps_completed = [*wf.steps_completed, step]
        else:
            wf.steps_completed = [step]
        await db.flush()
        await event_manager.broadcast(
            {
                "type": "workflow_step",
                "workflow_id": wf.id,
                "machine_id": wf.machine_id,
                "step": step,
                "status": status,
            }
        )

    async def _save_checkpoint(
        self, db: AsyncSession, wf: Workflow, step: str, data: dict | None = None
    ):
        """Save a checkpoint so the workflow can resume from this step on failure."""
        wf.last_checkpoint = step
        wf.checkpoint_data = data or {}
        await db.flush()

    def _should_skip_step(self, wf: Workflow, step: str) -> bool:
        """Check if a step was already completed (for resume)."""
        completed = wf.steps_completed or []
        return step in completed and wf.status == "resuming"

    async def resume_workflow(self, workflow_id: int):
        """Resume a failed workflow from its last checkpoint."""
        async with async_session() as db:
            wf = await db.get(Workflow, workflow_id)
            if not wf:
                raise ValueError(f"Workflow {workflow_id} not found")
            if wf.status != "failed":
                raise ValueError(f"Workflow {workflow_id} is {wf.status}, not failed")
            if wf.retry_count >= wf.max_retries:
                raise ValueError(
                    f"Workflow {workflow_id} exceeded max retries ({wf.max_retries})"
                )

            wf.retry_count += 1
            wf.status = "resuming"
            wf.error_message = None
            wf.completed_at = None
            await db.commit()

            machine = await db.get(Machine, wf.machine_id)
            if machine and machine.state == MachineState.ERROR:
                machine.error_message = None
                await db.commit()

        return await self.start_workflow(
            wf.machine_id, workflow_id, wf.workflow_type, wf.params or {}
        )

    async def run_enroll(self, machine_id: int, workflow_id: int):
        async with async_session() as db:
            machine = await db.get(Machine, machine_id)
            wf = await db.get(Workflow, workflow_id)
            try:
                await self._transition(db, machine, MachineState.ENROLLING)
                await self._update_workflow(db, wf, "connect_bmc")

                inventory = await enroll_discovered_host(
                    machine.bmc_ip, machine.bmc_username, machine.bmc_password
                )
                if "error" in inventory:
                    raise Exception(inventory["error"])

                await self._update_workflow(db, wf, "collect_inventory")

                machine.vendor = inventory.get("vendor")
                machine.model = inventory.get("model")
                machine.serial_number = inventory.get("serial_number")
                machine.bios_version = inventory.get("bios_version")
                machine.bmc_firmware = inventory.get("bmc_firmware")
                machine.cpu_info = inventory.get("cpu_info")
                machine.memory_gb = inventory.get("memory_gb")
                machine.network_info = inventory.get("network_info")
                machine.gpu_info = inventory.get("gpu_info")
                machine.gpu_count = inventory.get("gpu_count", 0)
                machine.tpm_info = inventory.get("tpm_info")
                machine.tpm_present = inventory.get("tpm_present", False)
                machine.power_state = inventory.get("power_state")
                machine.health_status = inventory.get("health_status")
                machine.last_seen = datetime.now(timezone.utc)

                await self._transition(db, machine, MachineState.ENROLLED)
                await self._update_workflow(db, wf, "complete", "completed")
                wf.completed_at = datetime.now(timezone.utc)
                wf.result = inventory
                await db.commit()

            except Exception as e:
                logger.exception(f"Enroll workflow failed for machine {machine_id}")
                machine.state = MachineState.ERROR
                machine.error_message = str(e)
                wf.status = "failed"
                wf.error_message = str(e)
                wf.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def run_provision(self, machine_id: int, workflow_id: int, params: dict):
        async with async_session() as db:
            machine = await db.get(Machine, machine_id)
            wf = await db.get(Workflow, workflow_id)
            try:
                await self._transition(db, machine, MachineState.PROVISIONING)

                client = RedfishClient(
                    machine.bmc_ip, machine.bmc_username, machine.bmc_password
                )
                async with client.session():
                    # Step 1: Configure BIOS if requested
                    if bios_attrs := params.get("bios_attributes"):
                        await self._update_workflow(db, wf, "configure_bios")
                        await client.set_bios_attributes(bios_attrs)

                    # Step 2: Configure RAID if requested
                    if raid_config := params.get("raid"):
                        await self._update_workflow(db, wf, "configure_storage")
                        await client.create_volume(
                            controller_id=raid_config["controller_id"],
                            name=raid_config.get("name", "OS_Volume"),
                            raid_level=raid_config["raid_level"],
                            drives=raid_config["drives"],
                        )

                    # Step 3: Set boot to PXE
                    await self._update_workflow(db, wf, "set_pxe_boot")
                    await client.set_boot_override(target="Pxe", mode="UEFI")

                    # Step 4: Mount ISO via virtual media if provided
                    if iso_url := params.get("iso_url"):
                        await self._update_workflow(db, wf, "mount_iso")
                        media = await client.get_virtual_media()
                        cd_slot = next(
                            (
                                m
                                for m in media
                                if "CD" in m.get("MediaTypes", [])
                                or "DVD" in m.get("MediaTypes", [])
                            ),
                            None,
                        )
                        if cd_slot:
                            managers = await client.get_managers()
                            mgr_id = managers[0].get("Id", "1") if managers else "1"
                            await client.mount_virtual_media(
                                mgr_id, cd_slot["Id"], iso_url
                            )
                            await client.set_boot_override(
                                target="Cd", mode="UEFI"
                            )

                    # Step 5: Power on
                    await self._update_workflow(db, wf, "power_on")
                    power = await client.get_power_state()
                    if power != "On":
                        await client.set_power_state("on")

                    # Step 6: Wait for OS (poll power state as proxy)
                    await self._update_workflow(db, wf, "wait_for_os")
                    await asyncio.sleep(10)

                    # Step 7: Refresh inventory
                    await self._update_workflow(db, wf, "refresh_inventory")
                    system = await client.get_system()
                    machine.power_state = system.get("PowerState")
                    machine.health_status = system.get("Status", {}).get("Health")
                    machine.os_installed = params.get("os_name", "Unknown")
                    machine.last_seen = datetime.now(timezone.utc)

                await self._transition(db, machine, MachineState.READY)
                await self._update_workflow(db, wf, "complete", "completed")
                wf.completed_at = datetime.now(timezone.utc)
                wf.result = {"os": params.get("os_name"), "status": "provisioned"}
                await db.commit()

            except Exception as e:
                logger.exception(f"Provision workflow failed for machine {machine_id}")
                machine.state = MachineState.ERROR
                machine.error_message = str(e)
                wf.status = "failed"
                wf.error_message = str(e)
                wf.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def run_decommission(self, machine_id: int, workflow_id: int):
        async with async_session() as db:
            machine = await db.get(Machine, machine_id)
            wf = await db.get(Workflow, workflow_id)
            try:
                await self._transition(db, machine, MachineState.DECOMMISSIONING)

                client = RedfishClient(
                    machine.bmc_ip, machine.bmc_username, machine.bmc_password
                )
                async with client.session():
                    await self._update_workflow(db, wf, "power_off")
                    await client.set_power_state("off")
                    await asyncio.sleep(5)

                    await self._update_workflow(db, wf, "clear_boot_override")
                    await client.set_boot_override(
                        target="None", mode="UEFI", enabled="Disabled"
                    )

                    await self._update_workflow(db, wf, "clear_logs")
                    try:
                        await client.clear_system_logs()
                    except Exception:
                        pass

                await self._transition(db, machine, MachineState.DECOMMISSIONED)
                await self._update_workflow(db, wf, "complete", "completed")
                wf.completed_at = datetime.now(timezone.utc)
                await db.commit()

            except Exception as e:
                logger.exception(
                    f"Decommission workflow failed for machine {machine_id}"
                )
                machine.state = MachineState.ERROR
                machine.error_message = str(e)
                wf.status = "failed"
                wf.error_message = str(e)
                wf.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def run_health_check(self, machine_id: int, workflow_id: int):
        async with async_session() as db:
            machine = await db.get(Machine, machine_id)
            wf = await db.get(Workflow, workflow_id)
            try:
                client = RedfishClient(
                    machine.bmc_ip, machine.bmc_username, machine.bmc_password
                )
                async with client.session():
                    await self._update_workflow(db, wf, "check_power")
                    machine.power_state = await client.get_power_state()

                    await self._update_workflow(db, wf, "check_system")
                    system = await client.get_system()
                    machine.health_status = system.get("Status", {}).get("Health")

                    await self._update_workflow(db, wf, "check_thermal")
                    thermal = {}
                    try:
                        chassis = await client.get_chassis()
                        if chassis:
                            chassis_id = chassis[0].get("Id", "1")
                            thermal = await client.get_thermal(chassis_id)
                    except Exception:
                        pass

                    await self._update_workflow(db, wf, "check_firmware")
                    firmware = await client.get_firmware_inventory()

                    await self._update_workflow(db, wf, "check_gpus")
                    gpus = await client.get_gpus()
                    gpu_temps = []
                    if chassis_list := await client.get_chassis():
                        gpu_temps = await client.get_gpu_thermal(
                            chassis_list[0].get("Id", "1")
                        )
                    machine.gpu_info = gpus
                    machine.gpu_count = len(gpus)

                    await self._update_workflow(db, wf, "check_tpm")
                    tpm_modules = await client.get_trusted_modules()
                    machine.tpm_info = {"modules": tpm_modules}
                    machine.tpm_present = len(tpm_modules) > 0 and any(
                        m.get("status") == "Enabled" for m in tpm_modules
                    )

                machine.last_seen = datetime.now(timezone.utc)
                await self._update_workflow(db, wf, "complete", "completed")
                wf.completed_at = datetime.now(timezone.utc)
                wf.result = {
                    "power_state": machine.power_state,
                    "health": machine.health_status,
                    "temperatures": [
                        {
                            "name": t.get("Name"),
                            "reading": t.get("ReadingCelsius"),
                            "status": t.get("Status", {}).get("Health"),
                        }
                        for t in thermal.get("Temperatures", [])
                    ],
                    "firmware_count": len(firmware),
                    "gpu_count": len(gpus),
                    "gpus": [
                        {
                            "name": g.get("name"),
                            "manufacturer": g.get("manufacturer"),
                            "status": g.get("status"),
                        }
                        for g in gpus
                    ],
                    "gpu_temperatures": gpu_temps,
                    "tpm_present": machine.tpm_present,
                    "tpm_modules": tpm_modules,
                }
                await db.commit()

            except Exception as e:
                logger.exception(
                    f"Health check failed for machine {machine_id}"
                )
                wf.status = "failed"
                wf.error_message = str(e)
                wf.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def _run_ansible_step(
        self,
        db: AsyncSession,
        wf: Workflow,
        machine: Machine,
        step_name: str,
        playbook: str,
        extra_vars: dict | None = None,
    ) -> dict:
        """Run a single Ansible playbook as a workflow step."""
        from app.engine.ansible_runner import run_playbook, PlaybookError

        await self._update_workflow(db, wf, step_name)
        await event_manager.broadcast(
            {
                "type": "ansible_step",
                "workflow_id": wf.id,
                "machine_id": machine.id,
                "step": step_name,
                "playbook": playbook,
                "status": "running",
            }
        )

        vars_with_bmc = {
            "bmc_ip": machine.bmc_ip,
            "bmc_user": machine.bmc_username,
            "bmc_pass": machine.bmc_password,
            **(extra_vars or {}),
        }

        result = await run_playbook(
            playbook=playbook,
            extra_vars=vars_with_bmc,
            inventory_host=machine.bmc_ip,
        )

        await event_manager.broadcast(
            {
                "type": "ansible_step",
                "workflow_id": wf.id,
                "machine_id": machine.id,
                "step": step_name,
                "playbook": playbook,
                "status": "completed",
            }
        )
        return result

    async def run_custom(self, machine_id: int, workflow_id: int, params: dict):
        """Run a custom workflow with mixed Redfish and Ansible steps.

        params.steps is a list of step definitions:
        [
            {"type": "redfish", "action": "power_on"},
            {"type": "ansible", "playbook": "configure_ntp.yml", "vars": {"ntp_server": "pool.ntp.org"}},
            {"type": "redfish", "action": "set_bios", "attributes": {"BootMode": "UEFI"}},
            {"type": "ansible", "playbook": "deploy_os.yml"},
            {"type": "redfish", "action": "health_check"},
            {"type": "wait", "seconds": 30},
        ]
        """
        async with async_session() as db:
            machine = await db.get(Machine, machine_id)
            wf = await db.get(Workflow, workflow_id)
            steps = params.get("steps", [])
            step_results = []

            try:
                target_state = params.get("target_state")
                if target_state:
                    await self._transition(
                        db, machine, MachineState(target_state)
                    )

                resume_from = wf.last_checkpoint if wf.status == "resuming" else None
                skip_until_found = resume_from is not None

                for i, step in enumerate(steps):
                    step_type = step.get("type")
                    step_name = step.get("name", f"{step_type}_{i}")

                    if skip_until_found:
                        if step_name == resume_from:
                            skip_until_found = False
                        else:
                            step_results.append(
                                {"step": step_name, "type": step_type, "status": "skipped_on_resume"}
                            )
                            continue

                    if step_type == "ansible":
                        result = await self._run_ansible_step(
                            db,
                            wf,
                            machine,
                            step_name,
                            playbook=step["playbook"],
                            extra_vars=step.get("vars"),
                        )
                        step_results.append(
                            {"step": step_name, "type": "ansible", "status": "ok"}
                        )

                    elif step_type == "redfish":
                        await self._update_workflow(db, wf, step_name)
                        client = RedfishClient(
                            machine.bmc_ip,
                            machine.bmc_username,
                            machine.bmc_password,
                        )
                        async with client.session():
                            result = await self._execute_redfish_action(
                                client, step
                            )
                        step_results.append(
                            {"step": step_name, "type": "redfish", "status": "ok", "result": result}
                        )

                    elif step_type == "wait":
                        seconds = step.get("seconds", 10)
                        await self._update_workflow(db, wf, f"wait_{seconds}s")
                        await asyncio.sleep(seconds)
                        step_results.append(
                            {"step": step_name, "type": "wait", "seconds": seconds}
                        )

                    else:
                        raise ValueError(f"Unknown step type: {step_type}")

                    await self._save_checkpoint(db, wf, step_name)
                    await db.flush()

                final_state = params.get("final_state")
                if final_state:
                    await self._transition(
                        db, machine, MachineState(final_state)
                    )

                machine.last_seen = datetime.now(timezone.utc)
                await self._update_workflow(db, wf, "complete", "completed")
                wf.completed_at = datetime.now(timezone.utc)
                wf.result = {"steps": step_results}
                await db.commit()

            except Exception as e:
                logger.exception(f"Custom workflow failed for machine {machine_id}")
                machine.state = MachineState.ERROR
                machine.error_message = str(e)
                wf.status = "failed"
                wf.error_message = str(e)
                wf.completed_at = datetime.now(timezone.utc)
                wf.result = {"steps": step_results, "failed_at": len(step_results)}
                await db.commit()

    async def _execute_redfish_action(self, client: RedfishClient, step: dict) -> dict:
        action = step.get("action")
        match action:
            case "power_on":
                return await client.set_power_state("on")
            case "power_off":
                return await client.set_power_state("off")
            case "restart":
                return await client.set_power_state("restart")
            case "force_off":
                return await client.set_power_state("force_off")
            case "set_bios":
                return await client.set_bios_attributes(step.get("attributes", {}))
            case "set_boot_pxe":
                return await client.set_boot_override(target="Pxe", mode="UEFI")
            case "set_boot_disk":
                return await client.set_boot_override(target="Hdd", mode="UEFI")
            case "set_boot_cd":
                return await client.set_boot_override(target="Cd", mode="UEFI")
            case "mount_iso":
                media = await client.get_virtual_media()
                cd_slot = next(
                    (m for m in media if "CD" in m.get("MediaTypes", []) or "DVD" in m.get("MediaTypes", [])),
                    None,
                )
                if cd_slot:
                    managers = await client.get_managers()
                    mgr_id = managers[0].get("Id", "1") if managers else "1"
                    return await client.mount_virtual_media(mgr_id, cd_slot["Id"], step["iso_url"])
                return {"status": "no_cd_slot"}
            case "health_check":
                system = await client.get_system()
                return {"health": system.get("Status", {}).get("Health"), "power": system.get("PowerState")}
            case "get_inventory":
                system = await client.get_system()
                cpus = await client.get_processors()
                memory = await client.get_memory()
                nics = await client.get_network_interfaces()
                gpus = await client.get_gpus()
                return build_inventory(system, cpus, memory, nics, gpus)
            case "get_gpus":
                return await client.get_gpus()
            case "get_gpu_health":
                gpus = await client.get_gpus()
                chassis = await client.get_chassis()
                gpu_temps = []
                if chassis:
                    gpu_temps = await client.get_gpu_thermal(chassis[0].get("Id", "1"))
                return {"gpu_count": len(gpus), "gpus": gpus, "gpu_temperatures": gpu_temps}
            case "get_pcie_devices":
                return await client.get_pcie_devices()
            case "get_tpm":
                modules = await client.get_trusted_modules()
                policy = await client.get_tpm_policy()
                return {"modules": modules, "bios_policy": policy, "tpm_present": len(modules) > 0}
            case "firmware_update":
                return await client.update_firmware(step["image_uri"], step.get("targets"))
            case "enable_secure_boot":
                return await client.set_secure_boot(True)
            case "disable_secure_boot":
                return await client.set_secure_boot(False)
            case "reset_bmc":
                return await client.reset_bmc()
            case "clear_logs":
                return await client.clear_system_logs()
            case "raw":
                method = step.get("method", "get")
                if method == "get":
                    return await client.raw_get(step["path"])
                elif method == "post":
                    return await client.raw_post(step["path"], step.get("body"))
                elif method == "patch":
                    return await client.raw_patch(step["path"], step["body"])
            case _:
                raise ValueError(f"Unknown redfish action: {action}")

    async def start_workflow(
        self, machine_id: int, workflow_id: int, workflow_type: str, params: dict
    ):
        runners = {
            "enroll": lambda: self.run_enroll(machine_id, workflow_id),
            "provision": lambda: self.run_provision(machine_id, workflow_id, params),
            "decommission": lambda: self.run_decommission(machine_id, workflow_id),
            "health_check": lambda: self.run_health_check(machine_id, workflow_id),
            "custom": lambda: self.run_custom(machine_id, workflow_id, params),
        }
        runner = runners.get(workflow_type)
        if not runner:
            raise ValueError(f"Unknown workflow type: {workflow_type}")
        task = asyncio.create_task(runner())
        self._running[workflow_id] = task
        return workflow_id


workflow_engine = WorkflowEngine()
