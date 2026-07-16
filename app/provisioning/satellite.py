"""Red Hat Satellite integration via Foreman REST API.

Handles RHEL, Rocky, Alma, CentOS provisioning through Satellite's
host management, content views, and kickstart infrastructure.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SatelliteError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SatelliteClient:
    def __init__(self):
        self.base_url = settings.satellite_url.rstrip("/")
        self.auth = (settings.satellite_username, settings.satellite_password)
        self.org_id = settings.satellite_org_id
        self.location_id = settings.satellite_location_id
        self.verify = settings.satellite_verify_ssl

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v2",
            auth=self.auth,
            verify=self.verify,
            timeout=30,
            headers={"Content-Type": "application/json"},
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with self._client() as client:
            resp = await client.request(method, path, **kwargs)
            if resp.status_code >= 400:
                raise SatelliteError(resp.text, resp.status_code)
            return resp.json() if resp.content else {}

    async def get_hostgroups(self) -> list[dict]:
        data = await self._request("GET", "/hostgroups", params={
            "organization_id": self.org_id,
            "per_page": 100,
        })
        return data.get("results", [])

    async def get_operatingsystems(self) -> list[dict]:
        data = await self._request("GET", "/operatingsystems", params={"per_page": 100})
        return data.get("results", [])

    async def get_subnets(self) -> list[dict]:
        data = await self._request("GET", "/subnets", params={
            "organization_id": self.org_id,
            "per_page": 100,
        })
        return data.get("results", [])

    async def get_content_views(self) -> list[dict]:
        data = await self._request(
            "GET",
            f"/organizations/{self.org_id}/content_views",
            params={"per_page": 100},
        )
        return data.get("results", [])

    async def create_host(
        self,
        name: str,
        mac: str,
        hostgroup_id: int,
        operatingsystem_id: int | None = None,
        subnet_id: int | None = None,
        ip: str | None = None,
        build: bool = True,
        activation_key: str | None = None,
        content_view_id: int | None = None,
        extra_params: dict | None = None,
    ) -> dict:
        host_data = {
            "host": {
                "name": name,
                "hostgroup_id": hostgroup_id,
                "organization_id": self.org_id,
                "location_id": self.location_id,
                "build": build,
                "managed": True,
                "interfaces_attributes": [
                    {
                        "mac": mac,
                        "type": "Nic::Managed",
                        "primary": True,
                        "provision": True,
                    }
                ],
            }
        }

        if operatingsystem_id:
            host_data["host"]["operatingsystem_id"] = operatingsystem_id
        if subnet_id:
            host_data["host"]["interfaces_attributes"][0]["subnet_id"] = subnet_id
        if ip:
            host_data["host"]["interfaces_attributes"][0]["ip"] = ip
        if content_view_id:
            host_data["host"]["content_facet_attributes"] = {
                "content_view_id": content_view_id,
            }
        if activation_key:
            host_data["host"]["subscription_facet_attributes"] = {
                "activation_keys": [activation_key],
            }
        if extra_params:
            host_data["host"]["host_parameters_attributes"] = [
                {"name": k, "value": v} for k, v in extra_params.items()
            ]

        return await self._request("POST", "/hosts", json=host_data)

    async def get_host(self, host_id: int) -> dict:
        return await self._request("GET", f"/hosts/{host_id}")

    async def get_host_status(self, host_id: int) -> dict:
        host = await self.get_host(host_id)
        return {
            "id": host.get("id"),
            "name": host.get("name"),
            "build": host.get("build"),
            "installed_at": host.get("installed_at"),
            "global_status": host.get("global_status"),
            "build_status": host.get("build_status"),
        }

    async def set_build_mode(self, host_id: int, build: bool = True) -> dict:
        return await self._request(
            "PUT", f"/hosts/{host_id}", json={"host": {"build": build}}
        )

    async def mark_host_built(self, host_id: int) -> dict:
        return await self._request(
            "PUT", f"/hosts/{host_id}", json={"host": {"build": False}}
        )

    async def delete_host(self, host_id: int) -> dict:
        return await self._request("DELETE", f"/hosts/{host_id}")

    async def provision_host(
        self,
        hostname: str,
        mac_address: str,
        hostgroup_id: int,
        ip: str | None = None,
        subnet_id: int | None = None,
        operatingsystem_id: int | None = None,
        activation_key: str | None = None,
        content_view_id: int | None = None,
    ) -> dict:
        """Full provisioning flow: create host in build mode."""
        host = await self.create_host(
            name=hostname,
            mac=mac_address,
            hostgroup_id=hostgroup_id,
            operatingsystem_id=operatingsystem_id,
            subnet_id=subnet_id,
            ip=ip,
            build=True,
            activation_key=activation_key,
            content_view_id=content_view_id,
        )

        host_id = host.get("id")
        logger.info(f"Satellite host created: {hostname} (id={host_id}), build mode enabled")

        return {
            "satellite_host_id": host_id,
            "hostname": hostname,
            "status": "build_mode",
            "message": "Host registered in Satellite, PXE boot will trigger kickstart",
        }

    async def check_build_complete(self, host_id: int) -> bool:
        status = await self.get_host_status(host_id)
        return status.get("build") is False and status.get("installed_at") is not None
