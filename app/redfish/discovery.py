import asyncio
import ipaddress
import logging

import httpx

from app.redfish.client import RedfishClient, build_inventory

logger = logging.getLogger(__name__)


async def probe_host(
    ip: str, username: str, password: str, port: int, timeout: int
) -> dict | None:
    """Probe a single IP for Redfish service root."""
    base_url = f"https://{ip}:{port}" if port != 443 else f"https://{ip}"
    try:
        async with httpx.AsyncClient(
            verify=False, timeout=timeout
        ) as client:
            resp = await client.get(
                f"{base_url}/redfish/v1/",
                auth=(username, password),
            )
            if resp.status_code == 200:
                return {"ip": ip, "service_root": resp.json()}
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
        pass
    except Exception as e:
        logger.debug(f"Probe {ip} failed: {e}")
    return None


async def discover_subnet(
    subnet: str,
    username: str,
    password: str,
    port: int = 443,
    timeout: int = 5,
    concurrency: int = 50,
) -> list[dict]:
    """Scan a subnet for Redfish-enabled BMCs."""
    network = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in network.hosts()]

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_probe(ip: str):
        async with semaphore:
            return await probe_host(ip, username, password, port, timeout)

    results = await asyncio.gather(*[bounded_probe(ip) for ip in hosts])
    return [r for r in results if r is not None]


async def enroll_discovered_host(
    ip: str, username: str, password: str
) -> dict:
    """Connect to a discovered BMC and pull full inventory."""
    client = RedfishClient(ip, username, password)
    async with client.session():
        systems = await client.get_systems()
        if not systems:
            return {"ip": ip, "error": "No systems found"}

        system = systems[0]
        system_id = system.get("Id", "1")

        cpus = await client.get_processors(system_id)
        memory = await client.get_memory(system_id)
        nics = await client.get_network_interfaces(system_id)
        gpus = await client.get_gpus(system_id)
        tpm_modules = await client.get_trusted_modules(system_id)
        managers = await client.get_managers()

        inventory = build_inventory(system, cpus, memory, nics, gpus)
        inventory["tpm_info"] = {"modules": tpm_modules}
        inventory["tpm_present"] = len(tpm_modules) > 0 and any(
            m.get("status") == "Enabled" for m in tpm_modules
        )

        if managers:
            inventory["bmc_firmware"] = managers[0].get("FirmwareVersion")

        return {"ip": ip, **inventory}
