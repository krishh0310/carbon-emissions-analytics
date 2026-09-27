"""Argon2 hashing, JWT access (15 min) + refresh (7 d) with rotation, role guard."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import RefreshToken, User, get_db

ph = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = ph.hash("timing-equaliser")


def hash_password(p: str) -> str:
    return ph.hash(p)


def verify_password(h: str | None, p: str) -> bool:
    try:
        return ph.verify(h or DUMMY_HASH, p) and h is not None  # always hash -> no user-enumeration timing leak
    except VerificationError:
        return False


def _encode(claims: dict, ttl: timedelta) -> str:
    n = datetime.now(UTC)
    return jwt.encode({**claims, "iat": n, "exp": n + ttl}, settings().jwt_secret, settings().jwt_algorithm)


def issue_tokens(db: Session, user: User) -> dict:
    s = settings()
    jti = uuid.uuid4().hex
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=s.refresh_days)))
    db.commit()
    return {"access_token": _encode({"sub": str(user.id), "role": user.role, "typ": "access"}, timedelta(minutes=s.access_minutes)),
            "refresh_token": _encode({"sub": str(user.id), "jti": jti, "typ": "refresh"}, timedelta(days=s.refresh_days)),
            "token_type": "bearer", "expires_in": s.access_minutes * 60}


def decode(token: str, typ: str) -> dict:
    try:
        c = jwt.decode(token, settings().jwt_secret, algorithms=[settings().jwt_algorithm], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from None
    if c.get("typ") != typ:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong token type")
    return c


def rotate(db: Session, refresh_token: str) -> dict:
    c = decode(refresh_token, "refresh")
    rt = db.get(RefreshToken, c.get("jti", ""))
    if rt is None or rt.user_id != int(c["sub"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown refresh token")
    if rt.revoked:  # reuse detected -> revoke every refresh token of this user
        db.execute(update(RefreshToken).where(RefreshToken.user_id == rt.user_id).values(revoked=True))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token reuse detected")
    rt.revoked = True
    user = db.get(User, rt.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user gone")
    return issue_tokens(db, user)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    c = decode(cred.credentials, "access")
    u = db.scalar(select(User).where(User.id == int(c["sub"])))
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return u


def require_admin(u: User = Depends(current_user)) -> User:
    if u.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return u
