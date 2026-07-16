from datetime import datetime
from pydantic import BaseModel


class FirmwareBaselineCreate(BaseModel):
    name: str
    description: str | None = None
    vendor_filter: str | None = None
    model_filter: str | None = None
    rules: dict
    is_active: bool = True


class FirmwareBaselineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    vendor_filter: str | None = None
    model_filter: str | None = None
    rules: dict | None = None
    is_active: bool | None = None


class FirmwareBaselineResponse(BaseModel):
    id: int
    name: str
    description: str | None
    vendor_filter: str | None
    model_filter: str | None
    rules: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComplianceFinding(BaseModel):
    component: str
    expected: str
    actual: str | None
    compliant: bool


class ComplianceReportResponse(BaseModel):
    id: int
    machine_id: int
    baseline_id: int
    status: str
    findings: list[dict] | None
    checked_at: datetime

    model_config = {"from_attributes": True}


class FleetComplianceSummary(BaseModel):
    total_machines: int
    compliant: int
    non_compliant: int
    unknown: int
    error: int
    compliance_rate: float
    by_baseline: dict[str, dict]
