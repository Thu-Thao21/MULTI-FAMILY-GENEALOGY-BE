from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.schemas.member_schemas import (
    ContactCreateIn,
    ContactUpdateIn,
    ContactOut,
    LifeEventCreateIn,
    LifeEventUpdateIn,
    LifeEventOut,
    MediaCreateIn,
    MediaUpdateIn,
    MediaOut,
    SkillCreateIn,
    SkillUpdateIn,
    SkillOut
)
from app.services import member_profile_service as profile_svc

router = APIRouter(prefix="/members", tags=["member_profile"])

# ─── Contacts ────────────────────────────────────────────────────────
@router.post("/{member_id}/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def add_contact(member_id: str, payload: ContactCreateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.add_member_contact(db, member_id, payload)

@router.put("/{member_id}/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(member_id: str, contact_id: str, payload: ContactUpdateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.update_member_contact(db, member_id, contact_id, payload)

@router.delete("/{member_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(member_id: str, contact_id: str, db: AsyncSession = Depends(get_db)):
    await profile_svc.delete_member_contact(db, member_id, contact_id)
    return None

# ─── Life Events ──────────────────────────────────────────────────────
@router.post("/{member_id}/life-events", response_model=LifeEventOut, status_code=status.HTTP_201_CREATED)
async def add_life_event(member_id: str, payload: LifeEventCreateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.add_member_life_event(db, member_id, payload)

@router.put("/{member_id}/life-events/{event_id}", response_model=LifeEventOut)
async def update_life_event(member_id: str, event_id: str, payload: LifeEventUpdateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.update_member_life_event(db, member_id, event_id, payload)

@router.delete("/{member_id}/life-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_life_event(member_id: str, event_id: str, db: AsyncSession = Depends(get_db)):
    await profile_svc.delete_member_life_event(db, member_id, event_id)
    return None

# ─── Media ───────────────────────────────────────────────────────────
@router.post("/{member_id}/media", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def add_media(member_id: str, payload: MediaCreateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.add_member_media(db, member_id, payload)

@router.put("/{member_id}/media/{media_id}", response_model=MediaOut)
async def update_media(member_id: str, media_id: str, payload: MediaUpdateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.update_member_media(db, member_id, media_id, payload)

@router.delete("/{member_id}/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(member_id: str, media_id: str, db: AsyncSession = Depends(get_db)):
    await profile_svc.delete_member_media(db, member_id, media_id)
    return None

# ─── Skills ──────────────────────────────────────────────────────────
@router.post("/{member_id}/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def add_skill(member_id: str, payload: SkillCreateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.add_member_skill(db, member_id, payload)

@router.put("/{member_id}/skills/{skill_id}", response_model=SkillOut)
async def update_skill(member_id: str, skill_id: str, payload: SkillUpdateIn, db: AsyncSession = Depends(get_db)):
    return await profile_svc.update_member_skill(db, member_id, skill_id, payload)

@router.delete("/{member_id}/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(member_id: str, skill_id: str, db: AsyncSession = Depends(get_db)):
    await profile_svc.delete_member_skill(db, member_id, skill_id)
    return None
