"""Auth service: password hashing, JWT token creation/verification, user dependency."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.users.models import PasswordResetToken, RefreshToken, User
from app.core.config import settings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days
RESET_TOKEN_EXPIRE_MINUTES = settings.password_reset_token_expire_minutes

# ---------------------------------------------------------------------------
# Password hashing (bcrypt trực tiếp — passlib không tương thích bcrypt >= 4.0)
# ---------------------------------------------------------------------------

def hash_password(plain_password: str) -> str:
    """Hash a plain-text password with bcrypt (cost factor 12)."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT access token
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Refresh token (stateful — lưu hash vào DB)
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    """SHA-256 hash của raw token — chỉ lưu hash, không lưu plaintext."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_refresh_token(user_id, db: AsyncSession) -> str:
    """
    Tạo refresh token mới cho user, lưu hash vào DB, trả về raw token.

    Raw token chỉ tồn tại trong response này — DB chỉ giữ hash.
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    db.add(RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    ))
    await db.commit()
    return raw_token


async def verify_and_rotate_refresh_token(
    raw_token: str,
    db: AsyncSession,
) -> User:
    """
    Xác thực refresh token, revoke token cũ, trả về User.
    Caller phải gọi create_refresh_token() sau để tạo token mới (rotation).

    Raises HTTPException 401 nếu token không hợp lệ / hết hạn / đã bị revoke.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token không hợp lệ hoặc đã hết hạn.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if rt is None or rt.revoked:
        raise invalid

    # Ép timezone-aware để so sánh
    expires_at = rt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise invalid

    # Revoke token cũ (rotation)
    rt.revoked = True
    await db.commit()

    # Load user
    user_result = await db.execute(select(User).where(User.id == rt.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Người dùng không tồn tại hoặc đã bị vô hiệu hóa.",
        )
    return user


async def revoke_refresh_token(raw_token: str, db: AsyncSession) -> None:
    """Revoke một refresh token khi user logout. Silent nếu token không tồn tại."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt and not rt.revoked:
        rt.revoked = True
        await db.commit()


# ---------------------------------------------------------------------------
# Password reset token (dùng một lần, hết hạn sau RESET_TOKEN_EXPIRE_MINUTES)
# ---------------------------------------------------------------------------

async def create_password_reset_token(user_id, db: AsyncSession) -> str:
    """
    Tạo password reset token mới, vô hiệu hoá token cũ chưa dùng của cùng user.
    Trả về raw token (thường sẽ gửi qua email; ở đây trả về cho demo).
    """
    now = datetime.now(timezone.utc)

    # Vô hiệu hoá token reset cũ chưa dùng của user này
    old_result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used.is_(False),
        )
    )
    for old_rt in old_result.scalars().all():
        old_rt.used = True

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    db.add(PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        used=False,
    ))
    await db.commit()
    return raw_token


async def verify_password_reset_token(raw_token: str, db: AsyncSession) -> User:
    """
    Xác thực reset token, đánh dấu đã dùng, trả về User để cập nhật mật khẩu.
    Raises HTTPException 400 nếu token không hợp lệ / hết hạn / đã dùng.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    prt = result.scalar_one_or_none()

    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Token không hợp lệ, đã được dùng hoặc đã hết hạn.",
    )

    if prt is None or prt.used:
        raise invalid

    expires_at = prt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise invalid

    # Đánh dấu đã dùng ngay để tránh replay
    prt.used = True
    await db.commit()

    user_result = await db.execute(select(User).where(User.id == prt.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Người dùng không tồn tại.")
    return user


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: return the authenticated User or raise 401."""
    payload = decode_access_token(token)
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa thông tin người dùng.",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Người dùng không tồn tại.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản đã bị vô hiệu hóa.")

    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Dependency: return User if token present and valid, else None (no error)."""
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: require admin role or raise 403."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ admin mới có quyền truy cập.",
        )
    return current_user
