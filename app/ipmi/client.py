"""IPMI fallback client for legacy BMCs that don't support Redfish.

Uses pyghmi for direct IPMI-over-LAN communication. This is the fallback
path — Redfish is always attempted first.
"""

import asyncio
import logging
from functools import partial

logger = logging.getLogger(__name__)


class IPMIError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class IPMIClient:
    """Async wrapper around pyghmi IPMI commands."""

    def __init__(self, host: str, username: str, password: str, port: int = 623):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._loop = None

    def _get_connection(self):
        try:
            from pyghmi.ipmi import command
        except ImportError:
            raise IPMIError("pyghmi not installed — run: pip install pyghmi")
        return command.Command(
            bmc=self.host,
            userid=self.username,
            password=self.password,
            port=self.port,
        )

    async def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def get_power_state(self) -> str:
        def _do():
            conn = self._get_connection()
            try:
                result = conn.get_power()
                return result.get("powerstate", "Unknown")
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to get power state: {e}")

    async def set_power_state(self, action: str) -> dict:
        actions = {
            "on": "on",
            "off": "off",
            "restart": "reset",
            "shutdown": "shutdown",
            "boot": "boot",
        }
        ipmi_action = actions.get(action)
        if not ipmi_action:
            raise IPMIError(f"Invalid IPMI power action: {action}")

        def _do():
            conn = self._get_connection()
            try:
                conn.set_power(ipmi_action, wait=False)
                return {"status": "ok", "action": ipmi_action}
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to set power state: {e}")

    async def get_sensor_data(self) -> list[dict]:
        def _do():
            conn = self._get_connection()
            try:
                sensors = []
                for name, data in conn.get_sensor_data().items():
                    sensors.append({
                        "name": name,
                        "value": data.get("value"),
                        "units": data.get("units", ""),
                        "states": data.get("states", []),
                        "health": data.get("health", 0),
                    })
                return sensors
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to read sensors: {e}")

    async def get_inventory(self) -> dict:
        def _do():
            conn = self._get_connection()
            try:
                inv = conn.get_inventory()
                result = {
                    "vendor": None,
                    "model": None,
                    "serial_number": None,
                }
                if "System" in inv:
                    sys_info = inv["System"]
                    if isinstance(sys_info, list) and sys_info:
                        sys_info = sys_info[0]
                    if isinstance(sys_info, dict):
                        result["vendor"] = sys_info.get("Manufacturer")
                        result["model"] = sys_info.get("Product name")
                        result["serial_number"] = sys_info.get("Serial Number")
                return result
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to get inventory: {e}")

    async def get_boot_device(self) -> dict:
        def _do():
            conn = self._get_connection()
            try:
                result = conn.get_bootdev()
                return {
                    "bootdev": result.get("bootdev", "Unknown"),
                    "persistent": result.get("persistent", False),
                    "uefimode": result.get("uefimode", False),
                }
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to get boot device: {e}")

    async def set_boot_device(
        self, device: str, persistent: bool = False, uefiboot: bool = True
    ) -> dict:
        def _do():
            conn = self._get_connection()
            try:
                conn.set_bootdev(device, persist=persistent, uefiboot=uefiboot)
                return {"status": "ok", "device": device}
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to set boot device: {e}")

    async def get_system_event_log(self) -> list[dict]:
        def _do():
            conn = self._get_connection()
            try:
                entries = []
                for entry in conn.get_event_log():
                    entries.append({
                        "id": entry.get("id"),
                        "timestamp": str(entry.get("timestamp", "")),
                        "message": entry.get("event", {}).get("event_data", ""),
                        "severity": entry.get("severity", ""),
                    })
                return entries
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to read event log: {e}")

    async def get_bmc_info(self) -> dict:
        def _do():
            conn = self._get_connection()
            try:
                info = conn.get_firmware()
                bmc_fw = None
                if isinstance(info, list):
                    for fw in info:
                        if isinstance(fw, dict) and "BMC" in fw.get("name", ""):
                            bmc_fw = fw.get("version")
                            break
                elif isinstance(info, dict):
                    bmc_fw = info.get("version")
                return {"bmc_firmware": bmc_fw}
            finally:
                conn.ipmi_session.logout()

        try:
            return await self._run_sync(_do)
        except Exception as e:
            raise IPMIError(f"Failed to get BMC info: {e}")


async def check_ipmi_available(host: str, username: str, password: str) -> bool:
    """Quick check if IPMI is reachable on a host."""
    client = IPMIClient(host, username, password)
    try:
        await client.get_power_state()
        return True
    except IPMIError:
        return False
