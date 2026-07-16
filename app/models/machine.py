import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MachineState(str, enum.Enum):
    DISCOVERED = "discovered"
    ENROLLING = "enrolling"
    ENROLLED = "enrolled"
    PROVISIONING = "provisioning"
    READY = "ready"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    DECOMMISSIONING = "decommissioning"
    DECOMMISSIONED = "decommissioned"
    ERROR = "error"


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bmc_ip: Mapped[str] = mapped_column(String(45), unique=True, nullable=False)
    bmc_username: Mapped[str] = mapped_column(String(255), nullable=False)
    bmc_password: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    state: Mapped[MachineState] = mapped_column(
        Enum(MachineState), default=MachineState.DISCOVERED
    )
    vendor: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(255))
    bios_version: Mapped[str | None] = mapped_column(String(100))
    bmc_firmware: Mapped[str | None] = mapped_column(String(100))
    cpu_info: Mapped[dict | None] = mapped_column(JSON)
    memory_gb: Mapped[int | None] = mapped_column(Integer)
    storage_info: Mapped[dict | None] = mapped_column(JSON)
    network_info: Mapped[dict | None] = mapped_column(JSON)
    gpu_info: Mapped[dict | None] = mapped_column(JSON)
    gpu_count: Mapped[int | None] = mapped_column(Integer, default=0)
    gpu_driver_version: Mapped[str | None] = mapped_column(String(100))
    tpm_info: Mapped[dict | None] = mapped_column(JSON)
    tpm_present: Mapped[bool | None] = mapped_column(default=False)
    health_status: Mapped[str | None] = mapped_column(String(50))
    power_state: Mapped[str | None] = mapped_column(String(20))
    os_installed: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[dict | None] = mapped_column(JSON, default=dict)
    rack_location: Mapped[str | None] = mapped_column(String(100))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    workflows: Mapped[list["Workflow"]] = relationship(back_populates="machine")
    events: Mapped[list["MachineEvent"]] = relationship(back_populates="machine")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    current_step: Mapped[str | None] = mapped_column(String(255))
    steps_completed: Mapped[dict | None] = mapped_column(JSON, default=list)
    steps_total: Mapped[dict | None] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_checkpoint: Mapped[str | None] = mapped_column(String(255))
    checkpoint_data: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    machine: Mapped["Machine"] = relationship(back_populates="workflows")


class MachineEvent(Base):
    __tablename__ = "machine_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(50))
    new_state: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    machine: Mapped["Machine"] = relationship(back_populates="events")


class BMCCredential(Base):
    __tablename__ = "bmc_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False)
