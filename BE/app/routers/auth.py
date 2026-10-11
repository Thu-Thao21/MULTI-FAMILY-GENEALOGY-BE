from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_account
from app.models.postgres import Account
from app.schemas.auth_schemas import AccountOut
from app.services.auth_service import format_account_me


router = APIRouter(prefix="/auth", tags=["auth"])


def firebase_account_response(account: Account) -> AccountOut:
    return format_account_me(account)


@router.post(
    "/register",
    response_model=AccountOut,
    summary="Register/bootstrap with Firebase ID token",
)
async def register_with_firebase(
    account: Account = Depends(get_current_account),
) -> AccountOut:
    """Create or resolve the Neon user represented by the Firebase bearer token."""
    return firebase_account_response(account)


@router.post(
    "/login",
    response_model=AccountOut,
    summary="Login with Firebase ID token",
)
async def login_with_firebase(
    account: Account = Depends(get_current_account),
) -> AccountOut:
    """Verify Firebase bearer token and return its canonical Neon user."""
    return firebase_account_response(account)


@router.post("/bootstrap", response_model=AccountOut)
async def bootstrap(
    account: Account = Depends(get_current_account),
) -> AccountOut:
    return firebase_account_response(account)


@router.get("/me", response_model=AccountOut)
async def get_me(
    account: Account = Depends(get_current_account),
) -> AccountOut:
    return firebase_account_response(account)
