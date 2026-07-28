from typing import List, Optional
from app.core.config import settings
from app.db.mongodb import get_database
from app.schemas.user import UserCreate
from bson import ObjectId

async def create_user(payload: UserCreate) -> dict:
    db = get_database(settings.MONGODB_DB)
    doc = payload.dict()
    result = await db["users"].insert_one(doc)
    doc_out = {"id": str(result.inserted_id), **doc}
    return doc_out

async def get_users() -> List[dict]:
    db = get_database(settings.MONGODB_DB)
    cursor = db["users"].find()
    results = []
    async for d in cursor:
        d["id"] = str(d.get("_id"))
        d.pop("_id", None)
        results.append(d)
    return results

async def get_user_by_id(user_id: str) -> Optional[dict]:
    db = get_database(settings.MONGODB_DB)
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    doc = await db["users"].find_one({"_id": oid})
    if not doc:
        return None
    doc["id"] = str(doc.get("_id"))
    doc.pop("_id", None)
    return doc
