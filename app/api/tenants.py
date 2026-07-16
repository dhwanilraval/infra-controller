from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, Role
from app.database import get_db
from app.models.tenant import Organization, Project, OrgMember
from app.schemas.tenant import (
    OrgCreate, OrgUpdate, OrgResponse,
    ProjectCreate, ProjectUpdate, ProjectResponse,
    MemberCreate, MemberUpdate, MemberResponse,
)

router = APIRouter(prefix="/api/v1", tags=["tenants"])


# ── Helpers ──


async def _get_org_and_check_access(org_slug: str, user, db, required_role=None):
    """Get org by slug and verify user has access."""
    result = await db.execute(
        select(Organization).where(
            Organization.slug == org_slug, Organization.is_active == True  # noqa: E712
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")

    # System admins (from auth.py Role.ADMIN) always have access
    if Role.ADMIN in user.roles:
        return org

    # Check membership
    member_result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org.id,
            OrgMember.user_sub == user.sub,
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(403, "Not a member of this organization")

    if required_role:
        role_hierarchy = {"owner": 4, "admin": 3, "operator": 2, "viewer": 1}
        if role_hierarchy.get(member.role, 0) < role_hierarchy.get(required_role, 0):
            raise HTTPException(
                403, f"Requires '{required_role}' role in this organization"
            )

    return org


# ── Organization Endpoints ──


@router.get("/orgs", response_model=list[OrgResponse])
async def list_orgs(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all orgs (filtered by membership unless system admin)."""
    if Role.ADMIN in user.roles:
        result = await db.execute(
            select(Organization).where(Organization.is_active == True)  # noqa: E712
        )
        return result.scalars().all()

    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_sub == user.sub, Organization.is_active == True)  # noqa: E712
    )
    return result.scalars().all()


@router.post("/orgs", response_model=OrgResponse, status_code=201)
async def create_org(
    body: OrgCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an organization. The creator becomes the owner."""
    org = Organization(name=body.name, slug=body.slug, description=body.description)
    db.add(org)
    await db.flush()

    member = OrgMember(
        org_id=org.id,
        user_sub=user.sub,
        user_email=user.email,
        user_name=user.name,
        role="owner",
    )
    db.add(member)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/orgs/{org_slug}", response_model=OrgResponse)
async def get_org(
    org_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_org_and_check_access(org_slug, user, db)


@router.patch("/orgs/{org_slug}", response_model=OrgResponse)
async def update_org(
    org_slug: str,
    body: OrgUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="admin")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)
    org.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/orgs/{org_slug}", status_code=204)
async def delete_org(
    org_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an organization (owner only)."""
    org = await _get_org_and_check_access(org_slug, user, db, required_role="owner")
    org.is_active = False
    org.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ── Project Endpoints ──


@router.get("/orgs/{org_slug}/projects", response_model=list[ProjectResponse])
async def list_projects(
    org_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db)
    result = await db.execute(
        select(Project).where(
            Project.org_id == org.id, Project.is_active == True  # noqa: E712
        )
    )
    return result.scalars().all()


@router.post(
    "/orgs/{org_slug}/projects", response_model=ProjectResponse, status_code=201
)
async def create_project(
    org_slug: str,
    body: ProjectCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="operator")
    project = Project(
        org_id=org.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get(
    "/orgs/{org_slug}/projects/{project_slug}", response_model=ProjectResponse
)
async def get_project(
    org_slug: str,
    project_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db)
    result = await db.execute(
        select(Project).where(
            Project.org_id == org.id,
            Project.slug == project_slug,
            Project.is_active == True,  # noqa: E712
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch(
    "/orgs/{org_slug}/projects/{project_slug}", response_model=ProjectResponse
)
async def update_project(
    org_slug: str,
    project_slug: str,
    body: ProjectUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="operator")
    result = await db.execute(
        select(Project).where(
            Project.org_id == org.id,
            Project.slug == project_slug,
            Project.is_active == True,  # noqa: E712
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/orgs/{org_slug}/projects/{project_slug}", status_code=204)
async def delete_project(
    org_slug: str,
    project_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="admin")
    result = await db.execute(
        select(Project).where(
            Project.org_id == org.id,
            Project.slug == project_slug,
            Project.is_active == True,  # noqa: E712
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    project.is_active = False
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ── Member Endpoints ──


@router.get("/orgs/{org_slug}/members", response_model=list[MemberResponse])
async def list_members(
    org_slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db)
    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org.id)
    )
    return result.scalars().all()


@router.post("/orgs/{org_slug}/members", response_model=MemberResponse, status_code=201)
async def add_member(
    org_slug: str,
    body: MemberCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="admin")
    member = OrgMember(
        org_id=org.id,
        user_sub=body.user_sub,
        user_email=body.user_email,
        user_name=body.user_name,
        role=body.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.patch("/orgs/{org_slug}/members/{member_id}", response_model=MemberResponse)
async def update_member(
    org_slug: str,
    member_id: int,
    body: MemberUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="admin")
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.id == member_id, OrgMember.org_id == org.id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    member.role = body.role
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/orgs/{org_slug}/members/{member_id}", status_code=204)
async def remove_member(
    org_slug: str,
    member_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_and_check_access(org_slug, user, db, required_role="admin")
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.id == member_id, OrgMember.org_id == org.id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")

    await db.delete(member)
    await db.commit()
