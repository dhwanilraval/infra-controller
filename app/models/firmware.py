import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FirmwareBaseline(Base):
    """A compliance baseline defining expected firmware versions."""
    __tablename__ = "firmware_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    vendor_filter: Mapped[str | None] = mapped_column(String(100))  # e.g. "Dell" — only apply to this vendor
    model_filter: Mapped[str | None] = mapped_column(String(255))  # e.g. "PowerEdge R750" — only this model
    rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    # rules format: {"bios": "2.19.1", "bmc": "6.10.80.00", "components": {"NIC": "22.5.9", "RAID": "52.28.0"}}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ComplianceStatus(str, enum.Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"
    ERROR = "error"


class ComplianceReport(Base):
    """Result of checking a machine against a baseline."""
    __tablename__ = "compliance_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("firmware_baselines.id"), nullable=False)
    status: Mapped[ComplianceStatus] = mapped_column(
        Enum(ComplianceStatus), default=ComplianceStatus.UNKNOWN
    )
    findings: Mapped[dict | None] = mapped_column(JSON)
    # findings format: [{"component": "BIOS", "expected": "2.19.1", "actual": "2.18.0", "compliant": false}, ...]
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
