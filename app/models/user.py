# Optional: DB model helpers or ODM definitions can go here.
# For now the project uses Pydantic schemas and Motor for DB access.

from typing import Optional
from pydantic import BaseModel, EmailStr

class User(BaseModel):
    id: Optional[str]
    first_name: str
    last_name: str
    email: EmailStr
