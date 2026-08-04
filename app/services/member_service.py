from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres import (
    Family,
    Member,
    MemberContact,
    MemberLifeEvent,
    MemberMedia,
    MemberSkill,
    Skill,
)
from app.schemas.member_schemas import (
    ContactOut,
    FamilyOut,
    LifeEventOut,
    MediaOut,
    MemberDetailOut,
    MemberListOut,
    MemberOut,
    SkillOut,
)


async def get_members(
    db: AsyncSession,
    family_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> MemberListOut:
    """Return a paginated list of members with optional filters."""

    base = select(Member)

    if family_id:
        base = base.where(Member.family_id == family_id)

    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                Member.full_name.ilike(pattern),
                Member.other_name.ilike(pattern),
                Member.occupation.ilike(pattern),
                Member.branch.ilike(pattern),
            )
        )

    # Total count
    count_stmt = select(func.count()).select_from(base.subquery())
    total = await db.scalar(count_stmt) or 0

    total_pages = max(1, math.ceil(total / limit))

    # Fetch page
    stmt = (
        base.order_by(Member.generation, Member.display_order, Member.full_name)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = [
        MemberOut(
            id=m.id,
            familyId=m.family_id,
            fullName=m.full_name,
            otherName=m.other_name,
            gender=m.gender,
            birthDate=m.birth_date,
            deathDate=m.death_date,
            isAlive=m.is_alive,
            fatherId=m.father_id,
            motherId=m.mother_id,
            branch=m.branch,
            subBranch=m.sub_branch,
            generation=m.generation,
            occupation=m.occupation,
            education=m.education,
            avatarUrl=m.avatar_url,
            status=m.status,
        )
        for m in rows
    ]

    return MemberListOut(
        items=items,
        total=total,
        page=page,
        limit=limit,
        totalPages=total_pages,
    )


async def get_member_detail(db: AsyncSession, member_id: str) -> MemberDetailOut | None:
    """Return full member detail including contacts, life events, media, skills."""

    result = await db.execute(select(Member).where(Member.id == member_id))
    member = result.scalar_one_or_none()
    if not member:
        return None

    # Family name
    family_name = None
    if member.family_id:
        fam_result = await db.execute(select(Family.name).where(Family.id == member.family_id))
        family_name = fam_result.scalar_one_or_none()

    # Contacts
    contacts_result = await db.execute(
        select(MemberContact).where(MemberContact.member_id == member_id).order_by(MemberContact.is_primary.desc())
    )
    contacts = [
        ContactOut(
            id=c.id,
            contactType=c.contact_type,
            contactValue=c.contact_value,
            isPrimary=c.is_primary,
            isPublic=c.is_public,
            notes=c.notes,
        )
        for c in contacts_result.scalars().all()
    ]

    # Life events
    events_result = await db.execute(
        select(MemberLifeEvent).where(MemberLifeEvent.member_id == member_id).order_by(MemberLifeEvent.event_date)
    )
    life_events = [
        LifeEventOut(
            id=e.id,
            eventType=e.event_type,
            title=e.title,
            eventDate=e.event_date,
            description=e.description,
            location=e.location,
        )
        for e in events_result.scalars().all()
    ]

    # Media
    media_result = await db.execute(
        select(MemberMedia).where(MemberMedia.member_id == member_id).order_by(MemberMedia.sort_order)
    )
    media = [
        MediaOut(
            id=md.id,
            mediaType=md.media_type,
            mediaUrl=md.media_url,
            caption=md.caption,
            sortOrder=md.sort_order,
        )
        for md in media_result.scalars().all()
    ]

    # Skills (join with Skill table)
    skills_result = await db.execute(
        select(MemberSkill, Skill)
        .join(Skill, MemberSkill.skill_id == Skill.id)
        .where(MemberSkill.member_id == member_id)
    )
    skills = [
        SkillOut(
            id=ms.id,
            skillName=sk.name,
            category=sk.category,
            proficiencyLevel=ms.proficiency_level,
        )
        for ms, sk in skills_result.all()
    ]

    return MemberDetailOut(
        id=member.id,
        familyId=member.family_id,
        familyName=family_name,
        userId=member.user_id,
        fullName=member.full_name,
        otherName=member.other_name,
        gender=member.gender,
        birthDate=member.birth_date,
        deathDate=member.death_date,
        lunarDeathDate=member.lunar_death_date,
        isAlive=member.is_alive,
        burialPlace=member.burial_place,
        burialCoordinates=member.burial_coordinates,
        fatherId=member.father_id,
        motherId=member.mother_id,
        branch=member.branch,
        subBranch=member.sub_branch,
        displayOrder=member.display_order,
        status=member.status,
        occupation=member.occupation,
        education=member.education,
        bio=member.bio,
        avatarUrl=member.avatar_url,
        galleryPhotos=member.gallery_photos or [],
        careerHistory=member.career_history or [],
        contact=member.contact,
        privacySettings=member.privacy_settings,
        contribution=member.contribution,
        generation=member.generation,
        isPrimary=member.is_primary,
        createdAt=member.created_at,
        updatedAt=member.updated_at,
        contacts=contacts,
        lifeEvents=life_events,
        media=media,
        skills=skills,
    )


async def get_families(db: AsyncSession) -> list[FamilyOut]:
    """Return all families with member count."""

    stmt = select(Family).order_by(Family.name)
    result = await db.execute(stmt)
    families = result.scalars().all()

    output = []
    for f in families:
        count_stmt = select(func.count()).select_from(Member).where(Member.family_id == f.id)
        member_count = await db.scalar(count_stmt) or 0
        output.append(
            FamilyOut(
                id=f.id,
                name=f.name,
                founderName=f.founder_name,
                originPlace=f.origin_place,
                status=f.status,
                memberCount=member_count,
            )
        )

    return output
