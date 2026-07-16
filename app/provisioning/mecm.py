"""Microsoft MECM (formerly SCCM) integration via AdminService REST API.

Handles Windows Server provisioning through MECM's task sequences,
device collections, and OS deployment infrastructure.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MECMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class MECMClient:
    def __init__(self):
        self.base_url = settings.mecm_url.rstrip("/")
        self.client_id = settings.mecm_client_id
        self.client_secret = settings.mecm_client_secret
        self.tenant_id = settings.mecm_tenant_id
        self.site_code = settings.mecm_site_code
        self._token: str | None = None

    async def _get_token(self) -> str:
        if self._token:
            return self._token

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": f"{self.base_url}/.default",
                },
            )
            if resp.status_code != 200:
                raise MECMError(f"Auth failed: {resp.text}", resp.status_code)
            self._token = resp.json()["access_token"]
            return self._token

    def _admin_url(self, path: str) -> str:
        return f"{self.base_url}/AdminService/wmi/{path}"

    def _v2_url(self, path: str) -> str:
        return f"{self.base_url}/AdminService/v2/{path}"

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        token = await self._get_token()
        async with httpx.AsyncClient(
            timeout=30,
            verify=True,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        ) as client:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code >= 400:
                raise MECMError(resp.text, resp.status_code)
            return resp.json() if resp.content else {}

    async def get_task_sequences(self) -> list[dict]:
        data = await self._request("GET", self._wmi_url("SMS_TaskSequencePackage"))
        results = []
        for ts in data.get("value", []):
            results.append({
                "id": ts.get("PackageID"),
                "name": ts.get("Name"),
                "description": ts.get("Description"),
                "boot_image_id": ts.get("BootImageID"),
            })
        return results

    def _wmi_url(self, cls: str) -> str:
        return f"{self.base_url}/AdminService/wmi/{cls}"

    async def get_collections(self, collection_type: int = 2) -> list[dict]:
        """Get device collections (type=2) or user collections (type=1)."""
        data = await self._request(
            "GET",
            self._wmi_url("SMS_Collection"),
            params={"$filter": f"CollectionType eq {collection_type}"},
        )
        results = []
        for c in data.get("value", []):
            results.append({
                "id": c.get("CollectionID"),
                "name": c.get("Name"),
                "member_count": c.get("MemberCount"),
            })
        return results

    async def import_device(
        self,
        name: str,
        mac_address: str,
    ) -> dict:
        """Import a device into MECM by MAC address."""
        body = {
            "NetbiosName": name,
            "MACAddress": mac_address,
            "OverwriteExistingRecord": True,
        }
        result = await self._request(
            "POST",
            self._wmi_url("SMS_Site/ImportMachineEntry"),
            json=body,
        )
        resource_id = result.get("ResourceID") or result.get("value", 0)
        logger.info(f"MECM device imported: {name} MAC={mac_address} ResourceID={resource_id}")
        return {"resource_id": resource_id, "name": name}

    async def add_to_collection(self, collection_id: str, resource_id: int) -> dict:
        body = {
            "collectionRule": {
                "@odata.type": "#AdminService.SMS_CollectionRuleDirect",
                "ResourceID": resource_id,
                "RuleName": f"Resource-{resource_id}",
            },
        }
        result = await self._request(
            "POST",
            self._wmi_url(f"SMS_Collection('{collection_id}')/AdminService.AddMembershipRule"),
            json=body,
        )
        return {"status": "added", "collection_id": collection_id}

    async def create_deployment(
        self,
        task_sequence_id: str,
        collection_id: str,
    ) -> dict:
        body = {
            "PackageID": task_sequence_id,
            "CollectionID": collection_id,
            "DeploymentIntent": 1,  # Required
            "DesiredConfigType": 1,  # Required
            "OfferType": 0,  # Required mandatory
        }
        result = await self._request(
            "POST",
            self._wmi_url("SMS_Advertisement"),
            json=body,
        )
        deployment_id = result.get("AdvertisementID") or result.get("value", "")
        logger.info(f"MECM deployment created: TS={task_sequence_id} Collection={collection_id}")
        return {"deployment_id": deployment_id}

    async def get_deployment_status(self, deployment_id: str) -> dict:
        data = await self._request(
            "GET",
            self._wmi_url(f"SMS_Advertisement('{deployment_id}')"),
        )
        return {
            "deployment_id": deployment_id,
            "name": data.get("AdvertisementName"),
            "state": data.get("AssignedScheduleEnabled"),
        }

    async def get_device_status(self, resource_id: int) -> dict:
        """Check if a device has completed its task sequence."""
        data = await self._request(
            "GET",
            self._wmi_url("SMS_ClientAdvertisementStatus"),
            params={"$filter": f"ResourceID eq {resource_id}"},
        )
        entries = data.get("value", [])
        if not entries:
            return {"resource_id": resource_id, "status": "pending"}

        latest = entries[-1]
        state = latest.get("LastState", 0)
        status_map = {0: "pending", 1: "running", 2: "succeeded", 3: "failed"}
        return {
            "resource_id": resource_id,
            "status": status_map.get(state, "unknown"),
            "last_status_message": latest.get("LastStatusMessageName"),
        }

    async def set_pxe_variables(
        self,
        resource_id: int,
        task_sequence_id: str,
        variables: dict | None = None,
    ) -> dict:
        """Set PXE boot variables so MECM knows which TS to run on PXE boot."""
        machine_vars = [
            {"Name": "SMSTSPreferredAdvertID", "Value": task_sequence_id, "IsMasked": False},
        ]
        for k, v in (variables or {}).items():
            machine_vars.append({"Name": k, "Value": str(v), "IsMasked": False})

        result = await self._request(
            "POST",
            self._wmi_url(f"SMS_MachineSettings({resource_id})/AdminService.SetMachineVariables"),
            json={"MachineVariables": machine_vars},
        )
        return {"status": "ok", "variables_set": len(machine_vars)}

    async def provision_device(
        self,
        hostname: str,
        mac_address: str,
        task_sequence_id: str,
        collection_id: str,
        pxe_variables: dict | None = None,
    ) -> dict:
        """Full provisioning flow: import → add to collection → deploy TS → set PXE vars."""
        device = await self.import_device(hostname, mac_address)
        resource_id = device["resource_id"]

        await self.add_to_collection(collection_id, resource_id)
        deployment = await self.create_deployment(task_sequence_id, collection_id)
        await self.set_pxe_variables(resource_id, task_sequence_id, pxe_variables)

        logger.info(f"MECM provisioning configured for {hostname}")
        return {
            "resource_id": resource_id,
            "deployment_id": deployment["deployment_id"],
            "hostname": hostname,
            "status": "ready_for_pxe",
            "message": "Device imported, TS deployed. PXE boot will start Windows installation.",
        }

    async def check_deployment_complete(self, resource_id: int) -> bool:
        status = await self.get_device_status(resource_id)
        return status.get("status") == "succeeded"
