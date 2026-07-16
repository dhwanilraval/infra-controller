import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")
    members: Mapped[list["OrgMember"]] = relationship(back_populates="organization")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    organization: Mapped["Organization"] = relationship(back_populates="projects")

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_project_org_slug"),
    )


class OrgRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class OrgMember(Base):
    __tablename__ = "org_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_sub: Mapped[str] = mapped_column(String(255), nullable=False)  # JWT sub claim
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization: Mapped["Organization"] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("org_id", "user_sub", name="uq_org_member"),
    )
