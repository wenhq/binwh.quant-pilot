from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import AsyncSessionLocal
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth.config import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.services.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, key: str, value: str, max_age_seconds: int) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=max_age_seconds,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest):
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        user = User(
            username=body.username,
            hashed_password=hash_password(body.password),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return {"id": user.id, "username": user.username}


@router.post("/login")
async def login(request: Request, response: Response, body: LoginRequest):
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        if not user or not verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=400, detail="用户名或密码错误")
        access = create_access_token(user.username)
        refresh = create_refresh_token(user.username)
        _set_cookie(response, ACCESS_TOKEN_COOKIE, access, settings.access_token_expire_minutes * 60)
        _set_cookie(response, REFRESH_TOKEN_COOKIE, refresh, settings.refresh_token_expire_days * 86400)
        return {"username": user.username}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少 refresh token")
    try:
        payload = decode_token(refresh_token)
        username = payload.get("sub")
    except ValueError:
        raise HTTPException(status_code=401, detail="无效的 refresh token") from None
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="用户无效")
        access = create_access_token(user.username)
        _set_cookie(response, ACCESS_TOKEN_COOKIE, access, settings.access_token_expire_minutes * 60)
        return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(ACCESS_TOKEN_COOKIE)
    response.delete_cookie(REFRESH_TOKEN_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "is_active": current_user.is_active}
