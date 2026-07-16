from datetime import datetime
from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None


class OrgUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    is_active: bool | None = None


class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    settings: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    is_active: bool | None = None


class ProjectResponse(BaseModel):
    id: int
    org_id: int
    name: str
    slug: str
    description: str | None
    settings: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberCreate(BaseModel):
    user_sub: str
    user_email: str
    user_name: str | None = None
    role: str = "viewer"


class MemberUpdate(BaseModel):
    role: str


class MemberResponse(BaseModel):
    id: int
    org_id: int
    user_sub: str
    user_email: str
    user_name: str | None
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}
