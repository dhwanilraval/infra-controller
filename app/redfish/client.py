import ssl
from contextlib import asynccontextmanager

import httpx

from app.config import settings


class RedfishError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RedfishClient:
    """Async Redfish client for BMC communication. Vendor-agnostic via DMTF standard."""

    def __init__(self, host: str, username: str, password: str, port: int = 443):
        self.base_url = f"https://{host}:{port}" if port != 443 else f"https://{host}"
        self.username = username
        self.password = password
        self._client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def session(self):
        async with httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.username, self.password),
            verify=settings.redfish_verify_ssl,
            timeout=settings.redfish_default_timeout,
            headers={"Content-Type": "application/json"},
        ) as client:
            self._client = client
            yield self
            self._client = None

    async def _get(self, path: str) -> dict:
        resp = await self._client.get(path)
        if resp.status_code >= 400:
            raise RedfishError(resp.text, resp.status_code)
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> dict:
        resp = await self._client.post(path, json=body or {})
        if resp.status_code >= 400:
            raise RedfishError(resp.text, resp.status_code)
        return resp.json() if resp.content else {"status": resp.status_code}

    async def _patch(self, path: str, body: dict) -> dict:
        resp = await self._client.patch(path, json=body)
        if resp.status_code >= 400:
            raise RedfishError(resp.text, resp.status_code)
        return resp.json() if resp.content else {"status": resp.status_code}

    async def _delete(self, path: str) -> dict:
        resp = await self._client.delete(path)
        if resp.status_code >= 400:
            raise RedfishError(resp.text, resp.status_code)
        return {"status": resp.status_code}

    # ── Service Root ──

    async def get_service_root(self) -> dict:
        return await self._get("/redfish/v1/")

    # ── System Inventory ──

    async def get_systems(self) -> list[dict]:
        data = await self._get("/redfish/v1/Systems")
        members = data.get("Members", [])
        systems = []
        for member in members:
            system = await self._get(member["@odata.id"])
            systems.append(system)
        return systems

    async def get_system(self, system_id: str = "1") -> dict:
        return await self._get(f"/redfish/v1/Systems/{system_id}")

    async def get_processors(self, system_id: str = "1") -> list[dict]:
        data = await self._get(f"/redfish/v1/Systems/{system_id}/Processors")
        cpus = []
        for member in data.get("Members", []):
            cpu = await self._get(member["@odata.id"])
            cpus.append(cpu)
        return cpus

    async def get_memory(self, system_id: str = "1") -> list[dict]:
        data = await self._get(f"/redfish/v1/Systems/{system_id}/Memory")
        dimms = []
        for member in data.get("Members", []):
            dimm = await self._get(member["@odata.id"])
            dimms.append(dimm)
        return dimms

    async def get_network_interfaces(self, system_id: str = "1") -> list[dict]:
        data = await self._get(f"/redfish/v1/Systems/{system_id}/EthernetInterfaces")
        nics = []
        for member in data.get("Members", []):
            nic = await self._get(member["@odata.id"])
            nics.append(nic)
        return nics

    # ── Power Management ──

    async def get_power_state(self, system_id: str = "1") -> str:
        system = await self.get_system(system_id)
        return system.get("PowerState", "Unknown")

    async def set_power_state(self, action: str, system_id: str = "1") -> dict:
        reset_types = {
            "on": "On",
            "off": "GracefulShutdown",
            "force_off": "ForceOff",
            "restart": "GracefulRestart",
            "force_restart": "ForceRestart",
            "nmi": "Nmi",
        }
        reset_type = reset_types.get(action)
        if not reset_type:
            raise RedfishError(f"Invalid power action: {action}")
        return await self._post(
            f"/redfish/v1/Systems/{system_id}/Actions/ComputerSystem.Reset",
            {"ResetType": reset_type},
        )

    # ── BIOS ──

    async def get_bios(self, system_id: str = "1") -> dict:
        return await self._get(f"/redfish/v1/Systems/{system_id}/Bios")

    async def get_bios_attributes(self, system_id: str = "1") -> dict:
        bios = await self.get_bios(system_id)
        return bios.get("Attributes", {})

    async def set_bios_attributes(
        self, attributes: dict, system_id: str = "1"
    ) -> dict:
        return await self._patch(
            f"/redfish/v1/Systems/{system_id}/Bios/Settings",
            {"Attributes": attributes},
        )

    async def get_boot_order(self, system_id: str = "1") -> dict:
        system = await self.get_system(system_id)
        return {
            "boot_order": system.get("Boot", {}).get(
                "BootSourceOverrideTarget", "None"
            ),
            "boot_mode": system.get("Boot", {}).get("BootSourceOverrideMode", "UEFI"),
            "boot_enabled": system.get("Boot", {}).get(
                "BootSourceOverrideEnabled", "Disabled"
            ),
        }

    async def set_boot_override(
        self,
        target: str,
        mode: str = "UEFI",
        enabled: str = "Once",
        system_id: str = "1",
    ) -> dict:
        return await self._patch(
            f"/redfish/v1/Systems/{system_id}",
            {
                "Boot": {
                    "BootSourceOverrideTarget": target,
                    "BootSourceOverrideMode": mode,
                    "BootSourceOverrideEnabled": enabled,
                }
            },
        )

    # ── Storage / RAID ──

    async def get_storage_controllers(self, system_id: str = "1") -> list[dict]:
        data = await self._get(f"/redfish/v1/Systems/{system_id}/Storage")
        controllers = []
        for member in data.get("Members", []):
            ctrl = await self._get(member["@odata.id"])
            controllers.append(ctrl)
        return controllers

    async def get_drives(self, system_id: str = "1") -> list[dict]:
        controllers = await self.get_storage_controllers(system_id)
        drives = []
        for ctrl in controllers:
            for drive_ref in ctrl.get("Drives", []):
                drive = await self._get(drive_ref["@odata.id"])
                drives.append(drive)
        return drives

    async def get_volumes(
        self, controller_id: str, system_id: str = "1"
    ) -> list[dict]:
        data = await self._get(
            f"/redfish/v1/Systems/{system_id}/Storage/{controller_id}/Volumes"
        )
        volumes = []
        for member in data.get("Members", []):
            vol = await self._get(member["@odata.id"])
            volumes.append(vol)
        return volumes

    async def create_volume(
        self,
        controller_id: str,
        name: str,
        raid_level: str,
        drives: list[str],
        system_id: str = "1",
    ) -> dict:
        body = {
            "Name": name,
            "RAIDType": raid_level,
            "Links": {"Drives": [{"@odata.id": d} for d in drives]},
        }
        return await self._post(
            f"/redfish/v1/Systems/{system_id}/Storage/{controller_id}/Volumes",
            body,
        )

    async def delete_volume(
        self, controller_id: str, volume_id: str, system_id: str = "1"
    ) -> dict:
        return await self._delete(
            f"/redfish/v1/Systems/{system_id}/Storage/{controller_id}/Volumes/{volume_id}"
        )

    # ── GPU / PCIe Accelerators ──

    async def get_pcie_devices(self, system_id: str = "1") -> list[dict]:
        try:
            data = await self._get(f"/redfish/v1/Systems/{system_id}/PCIeDevices")
            devices = []
            for member in data.get("Members", []):
                device = await self._get(member["@odata.id"])
                devices.append(device)
            return devices
        except RedfishError:
            return []

    async def get_pcie_functions(
        self, device_id: str, system_id: str = "1"
    ) -> list[dict]:
        try:
            data = await self._get(
                f"/redfish/v1/Systems/{system_id}/PCIeDevices/{device_id}/PCIeFunctions"
            )
            functions = []
            for member in data.get("Members", []):
                func = await self._get(member["@odata.id"])
                functions.append(func)
            return functions
        except RedfishError:
            return []

    async def get_gpus(self, system_id: str = "1") -> list[dict]:
        """Discover GPUs via multiple Redfish paths — vendor-agnostic."""
        gpus = []

        # Method 1: PCIe devices — look for VGA/3D controllers (class 0x03)
        pcie_devices = await self.get_pcie_devices(system_id)
        for device in pcie_devices:
            device_class = device.get("DeviceClass", "")
            name = device.get("Name", "")
            manufacturer = device.get("Manufacturer", "")

            is_gpu = (
                "DisplayController" in device_class
                or "GPU" in name.upper()
                or "NVIDIA" in manufacturer.upper()
                or "AMD" in manufacturer.upper()
                or "A100" in name
                or "H100" in name
                or "V100" in name
                or "A10" in name
                or "L40" in name
                or "T4" in name
            )

            if is_gpu:
                functions = await self.get_pcie_functions(
                    device.get("Id", ""), system_id
                )
                gpu = {
                    "id": device.get("Id"),
                    "name": name,
                    "manufacturer": manufacturer,
                    "model": device.get("Model"),
                    "serial_number": device.get("SerialNumber"),
                    "part_number": device.get("PartNumber"),
                    "firmware_version": device.get("FirmwareVersion"),
                    "status": device.get("Status", {}).get("Health"),
                    "pcie_slot": device.get("Slot", {}).get("SlotNumber"),
                    "device_class": device_class,
                    "pcie_functions": [
                        {
                            "id": f.get("Id"),
                            "class_code": f.get("ClassCode"),
                            "device_id": f.get("DeviceId"),
                            "vendor_id": f.get("VendorId"),
                            "subsystem_id": f.get("SubsystemId"),
                        }
                        for f in functions
                    ],
                }
                gpus.append(gpu)

        # Method 2: Processors of type "GPU" (some vendors list GPUs here)
        if not gpus:
            try:
                cpus = await self.get_processors(system_id)
                for cpu in cpus:
                    proc_type = cpu.get("ProcessorType", "")
                    if proc_type in ("GPU", "Accelerator", "OEM"):
                        gpus.append(
                            {
                                "id": cpu.get("Id"),
                                "name": cpu.get("Model", cpu.get("Name", "")),
                                "manufacturer": cpu.get("Manufacturer"),
                                "model": cpu.get("Model"),
                                "serial_number": cpu.get("SerialNumber"),
                                "part_number": cpu.get("PartNumber"),
                                "firmware_version": None,
                                "status": cpu.get("Status", {}).get("Health"),
                                "cores": cpu.get("TotalCores"),
                                "processor_type": proc_type,
                            }
                        )
            except RedfishError:
                pass

        return gpus

    async def get_gpu_thermal(self, chassis_id: str = "1") -> list[dict]:
        """Extract GPU-specific temperatures from thermal data."""
        try:
            thermal = await self.get_thermal(chassis_id)
            gpu_temps = []
            for temp in thermal.get("Temperatures", []):
                name = temp.get("Name", "").upper()
                if any(kw in name for kw in ["GPU", "NVIDIA", "ACCELERATOR", "GFX"]):
                    gpu_temps.append(
                        {
                            "name": temp.get("Name"),
                            "reading_celsius": temp.get("ReadingCelsius"),
                            "upper_threshold": temp.get("UpperThresholdCritical"),
                            "status": temp.get("Status", {}).get("Health"),
                        }
                    )
            return gpu_temps
        except RedfishError:
            return []

    # ── TPM / Trusted Modules ──

    async def get_trusted_modules(self, system_id: str = "1") -> list[dict]:
        """Read TPM status from Redfish TrustedModules array on the system."""
        try:
            system = await self.get_system(system_id)
            modules = system.get("TrustedModules", [])
            result = []
            for mod in modules:
                result.append({
                    "interface_type": mod.get("InterfaceType"),
                    "firmware_version": mod.get("FirmwareVersion"),
                    "firmware_version_2": mod.get("FirmwareVersion2"),
                    "status": mod.get("Status", {}).get("State"),
                    "interface_type_selection": mod.get("InterfaceTypeSelection"),
                })
            return result
        except RedfishError:
            return []

    async def get_tpm_policy(self, system_id: str = "1") -> dict:
        """Read BIOS-level TPM attributes (vendor-dependent attribute names)."""
        try:
            attrs = await self.get_bios_attributes(system_id)
            tpm_attrs = {}
            for key, value in attrs.items():
                key_upper = key.upper()
                if any(kw in key_upper for kw in ["TPM", "TRUSTED", "TXT"]):
                    tpm_attrs[key] = value
            return tpm_attrs
        except RedfishError:
            return {}

    # ── Firmware ──

    async def get_firmware_inventory(self) -> list[dict]:
        data = await self._get("/redfish/v1/UpdateService/FirmwareInventory")
        items = []
        for member in data.get("Members", []):
            item = await self._get(member["@odata.id"])
            items.append(item)
        return items

    async def update_firmware(
        self, image_uri: str, targets: list[str] | None = None
    ) -> dict:
        body = {"ImageURI": image_uri}
        if targets:
            body["Targets"] = targets
        return await self._post(
            "/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate",
            body,
        )

    # ── Chassis / Sensors / Health ──

    async def get_chassis(self) -> list[dict]:
        data = await self._get("/redfish/v1/Chassis")
        items = []
        for member in data.get("Members", []):
            item = await self._get(member["@odata.id"])
            items.append(item)
        return items

    async def get_thermal(self, chassis_id: str = "1") -> dict:
        return await self._get(f"/redfish/v1/Chassis/{chassis_id}/Thermal")

    async def get_power(self, chassis_id: str = "1") -> dict:
        return await self._get(f"/redfish/v1/Chassis/{chassis_id}/Power")

    # ── BMC / Manager ──

    async def get_managers(self) -> list[dict]:
        data = await self._get("/redfish/v1/Managers")
        items = []
        for member in data.get("Members", []):
            item = await self._get(member["@odata.id"])
            items.append(item)
        return items

    async def get_manager_network(self, manager_id: str = "1") -> list[dict]:
        data = await self._get(
            f"/redfish/v1/Managers/{manager_id}/EthernetInterfaces"
        )
        nics = []
        for member in data.get("Members", []):
            nic = await self._get(member["@odata.id"])
            nics.append(nic)
        return nics

    async def reset_bmc(self, manager_id: str = "1") -> dict:
        return await self._post(
            f"/redfish/v1/Managers/{manager_id}/Actions/Manager.Reset",
            {"ResetType": "GracefulRestart"},
        )

    # ── Logs ──

    async def get_system_logs(self, manager_id: str = "1") -> list[dict]:
        data = await self._get(
            f"/redfish/v1/Managers/{manager_id}/LogServices/Log1/Entries"
        )
        return data.get("Members", [])

    async def clear_system_logs(self, manager_id: str = "1") -> dict:
        return await self._post(
            f"/redfish/v1/Managers/{manager_id}/LogServices/Log1/Actions/LogService.ClearLog"
        )

    # ── Event Subscriptions ──

    async def get_event_subscriptions(self) -> list[dict]:
        data = await self._get("/redfish/v1/EventService/Subscriptions")
        subs = []
        for member in data.get("Members", []):
            sub = await self._get(member["@odata.id"])
            subs.append(sub)
        return subs

    async def create_event_subscription(
        self, destination: str, event_types: list[str]
    ) -> dict:
        return await self._post(
            "/redfish/v1/EventService/Subscriptions",
            {
                "Destination": destination,
                "Protocol": "Redfish",
                "EventTypes": event_types,
            },
        )

    # ── Virtual Media ──

    async def get_virtual_media(self, manager_id: str = "1") -> list[dict]:
        data = await self._get(f"/redfish/v1/Managers/{manager_id}/VirtualMedia")
        items = []
        for member in data.get("Members", []):
            item = await self._get(member["@odata.id"])
            items.append(item)
        return items

    async def mount_virtual_media(
        self, manager_id: str, media_id: str, image_uri: str
    ) -> dict:
        return await self._post(
            f"/redfish/v1/Managers/{manager_id}/VirtualMedia/{media_id}/Actions/VirtualMedia.InsertMedia",
            {"Image": image_uri, "Inserted": True},
        )

    async def unmount_virtual_media(
        self, manager_id: str, media_id: str
    ) -> dict:
        return await self._post(
            f"/redfish/v1/Managers/{manager_id}/VirtualMedia/{media_id}/Actions/VirtualMedia.EjectMedia",
        )

    # ── Secure Boot ──

    async def get_secure_boot(self, system_id: str = "1") -> dict:
        return await self._get(f"/redfish/v1/Systems/{system_id}/SecureBoot")

    async def set_secure_boot(
        self, enabled: bool, system_id: str = "1"
    ) -> dict:
        return await self._patch(
            f"/redfish/v1/Systems/{system_id}/SecureBoot",
            {"SecureBootEnable": enabled},
        )

    # ── Raw Redfish Access ──

    async def raw_get(self, path: str) -> dict:
        return await self._get(path)

    async def raw_post(self, path: str, body: dict | None = None) -> dict:
        return await self._post(path, body)

    async def raw_patch(self, path: str, body: dict) -> dict:
        return await self._patch(path, body)


def build_inventory(
    system: dict, cpus: list, memory: list, nics: list, gpus: list | None = None
) -> dict:
    total_memory_gb = sum(
        (m.get("CapacityMiB") or 0) for m in memory
    ) // 1024

    cpu_info = [
        {
            "name": c.get("Id"),
            "model": c.get("Model"),
            "cores": c.get("TotalCores"),
            "threads": c.get("TotalThreads"),
            "speed_mhz": c.get("MaxSpeedMHz"),
        }
        for c in cpus
    ]

    nic_info = [
        {
            "id": n.get("Id"),
            "mac": n.get("MACAddress"),
            "speed_mbps": n.get("SpeedMbps"),
            "status": n.get("Status", {}).get("State"),
        }
        for n in nics
    ]

    result = {
        "vendor": system.get("Manufacturer"),
        "model": system.get("Model"),
        "serial_number": system.get("SerialNumber"),
        "bios_version": system.get("BiosVersion"),
        "power_state": system.get("PowerState"),
        "health_status": system.get("Status", {}).get("Health"),
        "cpu_info": cpu_info,
        "memory_gb": total_memory_gb,
        "network_info": nic_info,
        "gpu_info": gpus or [],
        "gpu_count": len(gpus) if gpus else 0,
    }

    return result
