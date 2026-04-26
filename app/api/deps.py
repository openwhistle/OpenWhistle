"""Shared FastAPI dependencies."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Cookie, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import AdminRole, AdminUser
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

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    exp = auth_service.decode_access_token_exp(session_token)
    if exp is not None:
        request.state.session_expires_at = int(exp.timestamp())

    return user


def require_role(*roles: AdminRole) -> Callable[..., Coroutine[Any, Any, AdminUser]]:
    """Dependency factory: raises 403 if the current user doesn't have one of the given roles."""
    async def _check(current_user: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return current_user
    return _check


# Convenience aliases
require_admin = require_role(AdminRole.admin)
require_any_role = require_role(AdminRole.admin, AdminRole.case_manager)
