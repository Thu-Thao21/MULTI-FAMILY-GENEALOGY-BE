from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/users", tags=["users"])

# Example Pydantic model — extend as needed
class UserIn(BaseModel):
    first_name: str
    last_name: str
    email: str

class UserOut(UserIn):
    id: str

# Placeholder in-memory store for quick testing — replace with MongoDB calls
_fake_users = []

@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserIn):
    new = user.dict()
    new_id = str(len(_fake_users) + 1)
    new_doc = {"id": new_id, **new}
    _fake_users.append(new_doc)
    return new_doc

@router.get("/", response_model=List[UserOut])
async def list_users():
    return _fake_users

@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: str):
    for u in _fake_users:
        if u["id"] == user_id:
            return u
    raise HTTPException(status_code=404, detail="User not found")
