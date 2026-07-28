from fastapi import APIRouter, HTTPException, status
from typing import List
from app.schemas.user import UserCreate, UserOut
from app.services.user_service import create_user, get_users, get_user_by_id

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def api_create_user(payload: UserCreate):
    created = await create_user(payload)
    return created

@router.get("/", response_model=List[UserOut])
async def api_list_users():
    return await get_users()

@router.get("/{user_id}", response_model=UserOut)
async def api_get_user(user_id: str):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
