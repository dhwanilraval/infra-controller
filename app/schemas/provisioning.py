from datetime import datetime

from pydantic import BaseModel


class ProvisioningProfileCreate(BaseModel):
    name: str
    os_family: str
    os_version: str
    provision_method: str
    network_config: dict | None = None
    disk_config: dict | None = None
    packages: dict | None = None
    users_config: dict | None = None
    post_scripts: dict | None = None
    cluster_config: dict | None = None
    satellite_hostgroup_id: int | None = None
    satellite_content_view_id: int | None = None
    satellite_activation_key: str | None = None
    mecm_task_sequence_id: str | None = None
    mecm_collection_id: str | None = None
    vcenter_cluster_name: str | None = None
    vcenter_datastore: str | None = None
    config_template: str | None = None


class ProvisioningProfileUpdate(BaseModel):
    name: str | None = None
    network_config: dict | None = None
    disk_config: dict | None = None
    packages: dict | None = None
    users_config: dict | None = None
    post_scripts: dict | None = None
    cluster_config: dict | None = None
    satellite_hostgroup_id: int | None = None
    satellite_content_view_id: int | None = None
    satellite_activation_key: str | None = None
    mecm_task_sequence_id: str | None = None
    mecm_collection_id: str | None = None
    vcenter_cluster_name: str | None = None
    vcenter_datastore: str | None = None
    config_template: str | None = None


class ProvisioningProfileResponse(BaseModel):
    id: int
    name: str
    os_family: str
    os_version: str
    provision_method: str
    network_config: dict | None
    disk_config: dict | None
    packages: dict | None
    users_config: dict | None
    post_scripts: dict | None
    cluster_config: dict | None
    satellite_hostgroup_id: int | None
    satellite_content_view_id: int | None
    satellite_activation_key: str | None
    mecm_task_sequence_id: str | None
    mecm_collection_id: str | None
    vcenter_cluster_name: str | None
    vcenter_datastore: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProvisionRequest(BaseModel):
    profile_id: int
    hostname: str | None = None
    ip_address: str | None = None


class ProvisioningJobResponse(BaseModel):
    id: int
    machine_id: int
    profile_id: int
    workflow_id: int | None
    status: str
    hostname: str | None
    ip_address: str | None
    satellite_host_id: int | None
    mecm_deployment_id: str | None
    vcenter_task_id: str | None
    callback_received: bool | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class CallbackPayload(BaseModel):
    hostname: str | None = None
    machine_id: int | None = None
    status: str = "complete"
    message: str | None = None
    extra: dict | None = None
