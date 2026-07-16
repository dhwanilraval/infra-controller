import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OSFamily(str, enum.Enum):
    RHEL = "rhel"
    UBUNTU = "ubuntu"
    WINDOWS = "windows"
    ESXI = "esxi"
    COREOS = "coreos"
    FLATCAR = "flatcar"


class ProvisionMethod(str, enum.Enum):
    SATELLITE = "satellite"
    MECM = "mecm"
    VCENTER = "vcenter"
    IGNITION = "ignition"
    MANUAL = "manual"


class ProvisioningProfile(Base):
    __tablename__ = "provisioning_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    os_family: Mapped[OSFamily] = mapped_column(Enum(OSFamily), nullable=False)
    os_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provision_method: Mapped[ProvisionMethod] = mapped_column(
        Enum(ProvisionMethod), nullable=False
    )

    # Network
    network_config: Mapped[dict | None] = mapped_column(JSON)

    # Disk / storage layout
    disk_config: Mapped[dict | None] = mapped_column(JSON)

    # Packages / software
    packages: Mapped[dict | None] = mapped_column(JSON)

    # Users and SSH keys
    users_config: Mapped[dict | None] = mapped_column(JSON)

    # Post-install scripts or commands
    post_scripts: Mapped[dict | None] = mapped_column(JSON)

    # Cluster join config (K8s, vCenter, AD domain)
    cluster_config: Mapped[dict | None] = mapped_column(JSON)

    # External tool references
    satellite_hostgroup_id: Mapped[int | None] = mapped_column(Integer)
    satellite_content_view_id: Mapped[int | None] = mapped_column(Integer)
    satellite_activation_key: Mapped[str | None] = mapped_column(String(255))
    mecm_task_sequence_id: Mapped[str | None] = mapped_column(String(255))
    mecm_collection_id: Mapped[str | None] = mapped_column(String(255))
    vcenter_cluster_name: Mapped[str | None] = mapped_column(String(255))
    vcenter_datastore: Mapped[str | None] = mapped_column(String(255))

    # Ignition / cloud-init template (Jinja2 template string)
    config_template: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ProvisioningJob(Base):
    """Tracks a provisioning job tied to a machine + profile."""
    __tablename__ = "provisioning_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("provisioning_profiles.id"), nullable=False
    )
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflows.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    hostname: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    # External tool job IDs
    satellite_host_id: Mapped[int | None] = mapped_column(Integer)
    mecm_deployment_id: Mapped[str | None] = mapped_column(String(255))
    vcenter_task_id: Mapped[str | None] = mapped_column(String(255))

    # Rendered config (the actual answer file / ignition JSON served)
    rendered_config: Mapped[str | None] = mapped_column(Text)
    callback_received: Mapped[bool | None] = mapped_column(default=False)
    callback_data: Mapped[dict | None] = mapped_column(JSON)

    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
