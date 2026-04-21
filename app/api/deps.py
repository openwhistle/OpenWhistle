"""Shared FastAPI dependencies."""

from fastapi import Cookie, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import AdminUser
from app.redis_client import get_redis
from app.services import auth as auth_service


async def get_current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    session_token: str | None = Cookie(default=None, alias="ow_session"),
) -> AdminUser:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if not await auth_service.validate_session(redis, session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user_id = auth_service.decode_access_token(session_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return user
