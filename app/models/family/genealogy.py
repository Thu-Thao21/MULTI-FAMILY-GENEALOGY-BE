"""Genealogy domain models (Sprint 2 & 3).

Tables:
- branches (FamilyBranch)
- persons (Person)
- relationships (Relationship)
- person_closure (PersonClosure)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FamilyBranch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(
        "branch_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        "clan_id",
        UUID(as_uuid=True),
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.branch_id", ondelete="SET NULL"),
        nullable=True,
    )
    code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    branch_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), server_default="ACTIVE", default="ACTIVE", nullable=False)
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

    id: Mapped[uuid.UUID] = mapped_column(
        "person_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        "clan_id",
        UUID(as_uuid=True),
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.branch_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    death_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_alive: Mapped[Optional[bool]] = mapped_column(
        "is_living", Boolean, server_default="true", default=True, nullable=True
    )
    generation: Mapped[Optional[int]] = mapped_column(
        "generation_no", Integer, server_default="1", default=1, nullable=True
    )
    bio: Mapped[Optional[str]] = mapped_column("biography", Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(
        "avatar_storage_key", Text, nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), server_default="ACTIVE", default="ACTIVE", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
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


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        "relationship_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        "clan_id",
        UUID(as_uuid=True),
        ForeignKey("clans.clan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_member_id: Mapped[uuid.UUID] = mapped_column(
        "from_person_id",
        UUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_member_id: Mapped[uuid.UUID] = mapped_column(
        "to_person_id",
        UUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    child_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    marriage_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ended_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), server_default="ACTIVE", default="ACTIVE", nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
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


class PersonClosure(Base):
    __tablename__ = "person_closure"

    ancestor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        primary_key=True,
    )
    descendant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        primary_key=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# Aliases
Branch = FamilyBranch
