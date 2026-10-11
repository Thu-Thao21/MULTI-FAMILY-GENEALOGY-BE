from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


# Neon stores every canonical identifier as native UUID. SQLite keeps strings
# so unit tests can use readable fixture identifiers.
UUID_TYPE = String(36).with_variant(PG_UUID(as_uuid=False), "postgresql")


class Account(Base):
    """Firebase-backed identity mapped to Neon's canonical users table."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        "user_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    firebase_uid: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    username: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    phone_e164: Mapped[str | None] = mapped_column(
        "phone", String(255), unique=True, index=True, nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False, index=True
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    first_login_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    roles: Mapped[list["AccountRole"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        foreign_keys="AccountRole.account_id",
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        "role_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_role: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class AccountRole(Base):
    """Compatibility class name for a canonical user_roles row."""

    __tablename__ = "user_roles"

    id: Mapped[str] = mapped_column(
        "user_role_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        "user_id",
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("roles.role_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[str | None] = mapped_column(
        "clan_id",
        UUID_TYPE,
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    granted_by: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    account: Mapped[Account] = relationship(
        back_populates="roles", foreign_keys=[account_id]
    )
    role_record: Mapped[Role] = relationship(lazy="joined")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        "permission_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("roles.role_id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("permissions.permission_id", ondelete="CASCADE"),
        primary_key=True,
    )


class Family(Base):
    __tablename__ = "clans"

    id: Mapped[str] = mapped_column(
        "clan_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    registration_id: Mapped[str | None] = mapped_column(UUID_TYPE, nullable=True)
    clan_code: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        default=lambda: f"CLAN-{uuid4().hex[:12].upper()}",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    persons: Mapped[list["Person"]] = relationship(back_populates="family")


class FamilyMembership(Base):
    __tablename__ = "clan_memberships"

    id: Mapped[str] = mapped_column(
        "membership_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    family_id: Mapped[str] = mapped_column(
        "clan_id",
        UUID_TYPE,
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FamilyBranch(Base):
    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(
        "branch_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    family_id: Mapped[str] = mapped_column(
        "clan_id",
        UUID_TYPE,
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_branch_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("branches.branch_id", ondelete="SET NULL"),
        nullable=True,
    )
    code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(
        "person_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    family_id: Mapped[str] = mapped_column(
        "clan_id",
        UUID_TYPE,
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("branches.branch_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    death_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_alive: Mapped[bool | None] = mapped_column(
        "is_living", Boolean, default=True, nullable=True
    )
    generation: Mapped[int | None] = mapped_column(
        "generation_no", Integer, default=1, nullable=True
    )
    bio: Mapped[str | None] = mapped_column("biography", Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(
        "avatar_storage_key", Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    family: Mapped[Family] = relationship(back_populates="persons")


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(
        "relationship_id", UUID_TYPE, primary_key=True, default=lambda: str(uuid4())
    )
    family_id: Mapped[str] = mapped_column(
        "clan_id",
        UUID_TYPE,
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_member_id: Mapped[str] = mapped_column(
        "from_person_id",
        UUID_TYPE,
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_member_id: Mapped[str] = mapped_column(
        "to_person_id",
        UUID_TYPE,
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    child_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    marriage_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(255), default="ACTIVE", nullable=False
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PersonClosure(Base):
    __tablename__ = "person_closure"

    ancestor_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        primary_key=True,
    )
    descendant_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        primary_key=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# Domain aliases preserve existing service/controller names without declaring
# any legacy database table.
User = Account
UserRole = AccountRole
Branch = FamilyBranch
