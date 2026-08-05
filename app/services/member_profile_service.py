from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.postgres import (
    MemberContact,
    MemberLifeEvent,
    MemberMedia,
    Skill,
    MemberSkill
)
from app.schemas.member_schemas import (
    ContactCreateIn,
    ContactUpdateIn,
    LifeEventCreateIn,
    LifeEventUpdateIn,
    MediaCreateIn,
    MediaUpdateIn,
    SkillCreateIn,
    SkillUpdateIn,
    ContactOut,
    LifeEventOut,
    MediaOut,
    SkillOut
)

# ─── Contacts ────────────────────────────────────────────────────────
async def add_member_contact(db: AsyncSession, member_id: str, payload: ContactCreateIn) -> ContactOut:
    new_contact = MemberContact(
        id=str(uuid4()),
        member_id=member_id,
        contact_type=payload.contact_type,
        contact_value=payload.contact_value,
        is_primary=payload.is_primary,
        is_public=payload.is_public,
        notes=payload.notes
    )
    db.add(new_contact)
    await db.commit()
    await db.refresh(new_contact)
    return ContactOut.model_validate(new_contact)

async def update_member_contact(db: AsyncSession, member_id: str, contact_id: str, payload: ContactUpdateIn) -> ContactOut:
    result = await db.execute(select(MemberContact).where(MemberContact.id == contact_id, MemberContact.member_id == member_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(contact, field, value)
    
    await db.commit()
    await db.refresh(contact)
    return ContactOut.model_validate(contact)

async def delete_member_contact(db: AsyncSession, member_id: str, contact_id: str) -> bool:
    result = await db.execute(select(MemberContact).where(MemberContact.id == contact_id, MemberContact.member_id == member_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.delete(contact)
    await db.commit()
    return True

# ─── Life Events ──────────────────────────────────────────────────────
async def add_member_life_event(db: AsyncSession, member_id: str, payload: LifeEventCreateIn) -> LifeEventOut:
    new_event = MemberLifeEvent(
        id=str(uuid4()),
        member_id=member_id,
        event_type=payload.event_type,
        title=payload.title,
        event_date=payload.event_date,
        description=payload.description,
        location=payload.location
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)
    return LifeEventOut.model_validate(new_event)

async def update_member_life_event(db: AsyncSession, member_id: str, event_id: str, payload: LifeEventUpdateIn) -> LifeEventOut:
    result = await db.execute(select(MemberLifeEvent).where(MemberLifeEvent.id == event_id, MemberLifeEvent.member_id == member_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(event, field, value)
    
    await db.commit()
    await db.refresh(event)
    return LifeEventOut.model_validate(event)

async def delete_member_life_event(db: AsyncSession, member_id: str, event_id: str) -> bool:
    result = await db.execute(select(MemberLifeEvent).where(MemberLifeEvent.id == event_id, MemberLifeEvent.member_id == member_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    await db.delete(event)
    await db.commit()
    return True

# ─── Media ───────────────────────────────────────────────────────────
async def add_member_media(db: AsyncSession, member_id: str, payload: MediaCreateIn) -> MediaOut:
    new_media = MemberMedia(
        id=str(uuid4()),
        member_id=member_id,
        media_type=payload.media_type,
        media_url=payload.media_url,
        caption=payload.caption,
        sort_order=payload.sort_order
    )
    db.add(new_media)
    await db.commit()
    await db.refresh(new_media)
    return MediaOut.model_validate(new_media)

async def update_member_media(db: AsyncSession, member_id: str, media_id: str, payload: MediaUpdateIn) -> MediaOut:
    result = await db.execute(select(MemberMedia).where(MemberMedia.id == media_id, MemberMedia.member_id == member_id))
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(media, field, value)
    
    await db.commit()
    await db.refresh(media)
    return MediaOut.model_validate(media)

async def delete_member_media(db: AsyncSession, member_id: str, media_id: str) -> bool:
    result = await db.execute(select(MemberMedia).where(MemberMedia.id == media_id, MemberMedia.member_id == member_id))
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    await db.delete(media)
    await db.commit()
    return True

# ─── Skills ──────────────────────────────────────────────────────────
async def add_member_skill(db: AsyncSession, member_id: str, payload: SkillCreateIn) -> SkillOut:
    # Check if skill exists
    result = await db.execute(select(Skill).where(Skill.name == payload.skill_name))
    skill = result.scalar_one_or_none()
    if not skill:
        skill = Skill(
            id=str(uuid4()),
            name=payload.skill_name,
            category=payload.category
        )
        db.add(skill)
        await db.flush()
        
    # Create member skill
    new_member_skill = MemberSkill(
        id=str(uuid4()),
        member_id=member_id,
        skill_id=skill.id,
        proficiency_level=payload.proficiency_level
    )
    db.add(new_member_skill)
    await db.commit()
    await db.refresh(new_member_skill)
    return SkillOut(
        id=new_member_skill.id,
        skillName=skill.name,
        category=skill.category,
        proficiencyLevel=new_member_skill.proficiency_level
    )

async def update_member_skill(db: AsyncSession, member_id: str, member_skill_id: str, payload: SkillUpdateIn) -> SkillOut:
    result = await db.execute(select(MemberSkill).where(MemberSkill.id == member_skill_id, MemberSkill.member_id == member_id))
    member_skill = result.scalar_one_or_none()
    if not member_skill:
        raise HTTPException(status_code=404, detail="Member skill not found")
    
    member_skill.proficiency_level = payload.proficiency_level
    await db.commit()
    
    # Fetch skill info for returning
    skill_result = await db.execute(select(Skill).where(Skill.id == member_skill.skill_id))
    skill = skill_result.scalar_one()
    return SkillOut(
        id=member_skill.id,
        skillName=skill.name,
        category=skill.category,
        proficiencyLevel=member_skill.proficiency_level
    )

async def delete_member_skill(db: AsyncSession, member_id: str, member_skill_id: str) -> bool:
    result = await db.execute(select(MemberSkill).where(MemberSkill.id == member_skill_id, MemberSkill.member_id == member_id))
    member_skill = result.scalar_one_or_none()
    if not member_skill:
        raise HTTPException(status_code=404, detail="Member skill not found")
    await db.delete(member_skill)
    await db.commit()
    return True
