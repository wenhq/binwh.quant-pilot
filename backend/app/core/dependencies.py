from fastapi import HTTPException, Request, status

from app.models.user import User
from app.services.auth.security import decode_token
from sqlalchemy import select

from app.database import AsyncSessionLocal


async def get_current_user(request: Request) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未认证")
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        if username is None:
            raise ValueError("missing sub")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效凭证") from None

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户无效")
        return user
