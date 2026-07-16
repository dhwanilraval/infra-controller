from datetime import datetime

from pydantic import BaseModel, IPvAnyAddress


class MachineCreate(BaseModel):
    name: str
    bmc_ip: str
    bmc_username: str
    bmc_password: str
    rack_location: str | None = None
    tags: dict | None = None


class MachineUpdate(BaseModel):
    name: str | None = None
    bmc_username: str | None = None
    bmc_password: str | None = None
    rack_location: str | None = None
    tags: dict | None = None
    os_installed: str | None = None


class MachineResponse(BaseModel):
    id: int
    name: str
    bmc_ip: str
    state: str
    vendor: str | None
    model: str | None
    serial_number: str | None
    bios_version: str | None
    bmc_firmware: str | None
    cpu_info: dict | None
    memory_gb: int | None
    storage_info: dict | None
    network_info: dict | None
    gpu_info: dict | None
    gpu_count: int | None
    gpu_driver_version: str | None
    tpm_info: dict | None
    tpm_present: bool | None
    health_status: str | None
    power_state: str | None
    os_installed: str | None
    tags: dict | None
    rack_location: str | None
    last_seen: datetime | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None

    model_config = {"from_attributes": True}


class MachineSummary(BaseModel):
    id: int
    name: str
    bmc_ip: str
    state: str
    vendor: str | None
    model: str | None
    power_state: str | None
    health_status: str | None

    model_config = {"from_attributes": True}


class DiscoveryRequest(BaseModel):
    subnet: str
    bmc_username: str
    bmc_password: str
    port: int = 443


class DiscoveryResult(BaseModel):
    discovered: int
    machines: list[MachineSummary]
    errors: list[dict]


class PowerAction(BaseModel):
    action: str  # on, off, restart, force_off, force_restart


class BiosUpdate(BaseModel):
    attributes: dict[str, str | int | bool]


class FirmwareUpdate(BaseModel):
    image_uri: str
    targets: list[str] | None = None


class WorkflowCreate(BaseModel):
    workflow_type: str
    params: dict | None = None


class WorkflowResponse(BaseModel):
    id: int
    machine_id: int
    workflow_type: str
    status: str
    current_step: str | None
    steps_completed: list | None
    steps_total: list | None
    error_message: str | None
    params: dict | None
    result: dict | None
    retry_count: int
    max_retries: int
    last_checkpoint: str | None
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class EventResponse(BaseModel):
    id: int
    machine_id: int
    event_type: str
    previous_state: str | None
    new_state: str | None
    details: dict | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class HealthSummary(BaseModel):
    total_machines: int
    by_state: dict[str, int]
    by_health: dict[str, int]
    by_power: dict[str, int]
    by_vendor: dict[str, int]


class BMCCredentialCreate(BaseModel):
    label: str
    username: str
    password: str
    is_default: bool = False


class StorageVolumeCreate(BaseModel):
    name: str
    raid_level: str
    drives: list[str]
    capacity_gb: int | None = None
