"""Provisioning orchestrator — dispatches to the correct integration based on OS family.

This is the central coordinator that:
1. Takes a machine + provisioning profile
2. Calls our BMC layer for hardware prep (BIOS, RAID, boot order)
3. Delegates OS installation to the right external tool
4. Waits for completion callback
5. Transitions machine to READY
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.machine import Machine
from app.models.provisioning import ProvisioningJob, ProvisioningProfile, ProvisionMethod

logger = logging.getLogger(__name__)


class ProvisionOrchestrator:

    async def start_provision(
        self,
        db: AsyncSession,
        machine: Machine,
        profile: ProvisioningProfile,
        job: ProvisioningJob,
    ) -> dict:
        """Dispatch provisioning to the correct integration."""

        method = profile.provision_method
        result = {}

        match method:
            case ProvisionMethod.SATELLITE:
                result = await self._provision_satellite(machine, profile, job)
            case ProvisionMethod.MECM:
                result = await self._provision_mecm(machine, profile, job)
            case ProvisionMethod.VCENTER:
                result = await self._provision_vcenter(machine, profile, job)
            case ProvisionMethod.IGNITION:
                result = await self._provision_ignition(machine, profile, job)
            case ProvisionMethod.MANUAL:
                result = {"status": "manual", "message": "Manual provisioning — no external tool"}
            case _:
                raise ValueError(f"Unknown provision method: {method}")

        job.status = "os_deploying"
        await db.flush()

        return result

    async def _provision_satellite(
        self, machine: Machine, profile: ProvisioningProfile, job: ProvisioningJob
    ) -> dict:
        if not settings.satellite_enabled:
            raise ValueError("Red Hat Satellite integration is not enabled")

        from app.provisioning.satellite import SatelliteClient

        client = SatelliteClient()

        mac_address = _get_primary_mac(machine)
        hostname = job.hostname or machine.name

        result = await client.provision_host(
            hostname=hostname,
            mac_address=mac_address,
            hostgroup_id=profile.satellite_hostgroup_id,
            ip=job.ip_address,
            activation_key=profile.satellite_activation_key,
            content_view_id=profile.satellite_content_view_id,
        )

        job.satellite_host_id = result.get("satellite_host_id")
        logger.info(
            f"Satellite provisioning started for {hostname} "
            f"(satellite_host_id={job.satellite_host_id})"
        )
        return result

    async def _provision_mecm(
        self, machine: Machine, profile: ProvisioningProfile, job: ProvisioningJob
    ) -> dict:
        if not settings.mecm_enabled:
            raise ValueError("Microsoft MECM integration is not enabled")

        from app.provisioning.mecm import MECMClient

        client = MECMClient()

        mac_address = _get_primary_mac(machine)
        hostname = job.hostname or machine.name

        result = await client.provision_device(
            hostname=hostname,
            mac_address=mac_address,
            task_sequence_id=profile.mecm_task_sequence_id,
            collection_id=profile.mecm_collection_id,
        )

        job.mecm_deployment_id = result.get("deployment_id")
        logger.info(
            f"MECM provisioning started for {hostname} "
            f"(deployment_id={job.mecm_deployment_id})"
        )
        return result

    async def _provision_vcenter(
        self, machine: Machine, profile: ProvisioningProfile, job: ProvisioningJob
    ) -> dict:
        if not settings.vcenter_enabled:
            raise ValueError("VMware vCenter integration is not enabled")

        from app.provisioning.vcenter import VCenterClient

        client = VCenterClient()

        # For ESXi, the host IP is the BMC IP's management network peer
        # (or the IP assigned during ESXi installation).
        esxi_ip = job.ip_address or machine.bmc_ip

        result = await client.provision_esxi_host(
            esxi_ip=esxi_ip,
            cluster_name=profile.vcenter_cluster_name or settings.vcenter_cluster,
        )

        job.vcenter_task_id = result.get("vcenter_host_id")
        logger.info(
            f"vCenter provisioning started for {esxi_ip} "
            f"(vcenter_host_id={job.vcenter_task_id})"
        )
        return result

    async def _provision_ignition(
        self, machine: Machine, profile: ProvisioningProfile, job: ProvisioningJob
    ) -> dict:
        from app.provisioning.ignition import render_ignition_json, save_ignition_config

        hostname = job.hostname or machine.name
        users_config = profile.users_config or {}
        ssh_keys = users_config.get("ssh_keys", [])

        ip_config = None
        if profile.network_config:
            ip_config = {
                "ip": job.ip_address or profile.network_config.get("ip"),
                "prefix": profile.network_config.get("prefix", "24"),
                "gateway": profile.network_config.get("gateway"),
                "dns": profile.network_config.get("dns", []),
                "interface": profile.network_config.get("interface", "ens192"),
            }

        k8s_join = None
        if profile.cluster_config and profile.cluster_config.get("type") == "k8s":
            k8s_join = {
                "api_server": profile.cluster_config["api_server"],
                "token": profile.cluster_config["token"],
                "ca_hash": profile.cluster_config.get("ca_hash", ""),
            }

        config_json = render_ignition_json(
            hostname=hostname,
            ssh_keys=ssh_keys,
            ip_config=ip_config,
            users=users_config.get("users"),
            storage=profile.disk_config,
            k8s_join=k8s_join,
        )

        save_ignition_config(machine.id, config_json)
        job.rendered_config = config_json

        serve_url = f"{settings.callback_base_url}/api/v1/provision-files/{machine.id}/config.ign"
        logger.info(f"Ignition config generated for {hostname}: {serve_url}")

        return {
            "hostname": hostname,
            "ignition_url": serve_url,
            "status": "config_ready",
            "message": f"Ignition config served at {serve_url}. PXE boot with ignition.config.url={serve_url}",
        }

    async def check_status(
        self,
        job: ProvisioningJob,
        profile: ProvisioningProfile,
    ) -> dict:
        """Poll external tool for completion status."""
        match profile.provision_method:
            case ProvisionMethod.SATELLITE:
                if not job.satellite_host_id:
                    return {"status": "unknown"}
                from app.provisioning.satellite import SatelliteClient
                client = SatelliteClient()
                complete = await client.check_build_complete(job.satellite_host_id)
                return {"status": "complete" if complete else "in_progress"}

            case ProvisionMethod.MECM:
                if not job.mecm_deployment_id:
                    return {"status": "unknown"}
                from app.provisioning.mecm import MECMClient
                client = MECMClient()
                # We need the resource ID, not deployment ID for status check
                return {"status": "check_mecm_console"}

            case ProvisionMethod.VCENTER:
                if not job.vcenter_task_id:
                    return {"status": "unknown"}
                from app.provisioning.vcenter import VCenterClient
                client = VCenterClient()
                connected = await client.check_host_connected(job.vcenter_task_id)
                return {"status": "complete" if connected else "in_progress"}

            case ProvisionMethod.IGNITION:
                return {
                    "status": "complete" if job.callback_received else "waiting_for_callback"
                }

            case _:
                return {"status": "manual"}


def _get_primary_mac(machine: Machine) -> str:
    """Extract the primary MAC address from machine network info."""
    nics = machine.network_info or []
    if isinstance(nics, list):
        for nic in nics:
            mac = nic.get("mac")
            if mac:
                return mac
    raise ValueError(f"No MAC address found for machine {machine.id}")


orchestrator = ProvisionOrchestrator()
