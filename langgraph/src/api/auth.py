import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
import bcrypt as _bcrypt
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import Story, User
from api.deps import JWT_ALGORITHM, JWT_SECRET, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# ── In-memory rate limiter (per IP) ──────────────────────────────────────────
_attempts: dict[str, list[float]] = defaultdict(list)
_RL_WINDOW = 60   # seconds
_RL_MAX    = 10   # attempts per window

def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _attempts[ip] = [t for t in _attempts[ip] if now - t < _RL_WINDOW]
    if len(_attempts[ip]) >= _RL_MAX:
        raise HTTPException(status_code=429, detail="Too many attempts, please try again later")
    _attempts[ip].append(now)

_ACCESS_EXPIRE_MIN  = 15
_REFRESH_EXPIRE_DAYS = 7

COOKIE_SECURE:   bool = os.environ.get("COOKIE_SECURE",   "false").lower() == "true"
COOKIE_SAMESITE: str  = os.environ.get("COOKIE_SAMESITE", "lax")
GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(email: str) -> str:
    return email.strip().lower()

def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()

def _verify(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())

def _make_token(sub: str, token_type: str, expire: timedelta) -> str:
    return jwt.encode(
        {"sub": sub, "type": token_type, "exp": datetime.utcnow() + expire},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )

def _set_refresh_cookie(response: Response, user_id: str) -> None:
    token = _make_token(user_id, "refresh", timedelta(days=_REFRESH_EXPIRE_DAYS))
    response.set_cookie(
        "refresh_token", token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=_REFRESH_EXPIRE_DAYS * 24 * 3600,
    )

def _token_response(user: User) -> dict:
    return {
        "access_token": _make_token(str(user.id), "access", timedelta(minutes=_ACCESS_EXPIRE_MIN)),
        "token_type": "bearer",
        "user": _user_dict(user),
    }

def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "preferences": {
            "voice": user.pref_voice,
            "audience": user.pref_audience,
            "style": user.pref_style,
        },
        "daily_count": user.daily_count,
        "monthly_count": user.monthly_count,
    }


# ── Register ──────────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


@router.post("/register", status_code=201)
async def register(request: Request, body: RegisterBody, response: Response, db: AsyncSession = Depends(get_db)):
    _rate_limit(request)
    email = _normalize(body.email)
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")
    if len(body.password) < 5:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if len(body.password) > 128:
        raise HTTPException(status_code=422, detail="Password is too long")
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=email, hashed_password=_hash(body.password), display_name=body.display_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _set_refresh_cookie(response, str(user.id))
    return _token_response(user)


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(request: Request, body: LoginBody, response: Response, db: AsyncSession = Depends(get_db)):
    _rate_limit(request)
    email = _normalize(body.email)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not user.hashed_password or not _verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _set_refresh_cookie(response, str(user.id))
    return _token_response(user)


# ── Google OAuth ──────────────────────────────────────────────────────────────

class GoogleBody(BaseModel):
    id_token: str


@router.post("/google")
async def google_auth(body: GoogleBody, response: Response, db: AsyncSession = Depends(get_db)):
    import asyncio
    from google.oauth2 import id_token as gid
    from google.auth.transport import requests as greq

    loop = asyncio.get_running_loop()
    try:
        idinfo = await loop.run_in_executor(
            None, lambda: gid.verify_oauth2_token(body.id_token, greq.Request(), GOOGLE_CLIENT_ID)
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    if not idinfo.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google email not verified")

    google_id   = idinfo["sub"]
    email       = _normalize(idinfo["email"])
    display_name = idinfo.get("name")

    user = (await db.execute(select(User).where(User.google_id == google_id))).scalar_one_or_none()

    if not user:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            existing.google_id = google_id
            if not existing.display_name:
                existing.display_name = display_name
            user = existing
        else:
            user = User(email=email, google_id=google_id, display_name=display_name)
            db.add(user)

    await db.commit()
    await db.refresh(user)

    _set_refresh_cookie(response, str(user.id))
    return _token_response(user)


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    _set_refresh_cookie(response, str(user.id))
    return _token_response(user)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token", secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, path="/")
    return {"status": "ok"}


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me")
async def me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    story_count = (await db.execute(
        select(func.count()).select_from(Story).where(Story.user_id == current_user.id)
    )).scalar()
    return {**_user_dict(current_user), "story_count": story_count}


class PrefsBody(BaseModel):
    voice:    Optional[str] = None
    audience: Optional[str] = None
    style:    Optional[str] = None


@router.patch("/me")
async def update_me(
    body: PrefsBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.voice    is not None: current_user.pref_voice    = body.voice
    if body.audience is not None: current_user.pref_audience = body.audience
    if body.style    is not None: current_user.pref_style    = body.style
    await db.commit()
    await db.refresh(current_user)
    return _user_dict(current_user)


# ── Stories ───────────────────────────────────────────────────────────────────

@router.get("/stories")
async def get_stories(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    rows = (await db.execute(
        select(Story)
        .where(Story.user_id == current_user.id)
        .order_by(Story.created_at.desc())
        .offset(offset).limit(page_size)
    )).scalars().all()
    return [
        {
            "id": str(s.id),
            "topic": s.topic,
            "story_text": s.story_text,
            "audio_url": s.audio_url,
            "duration_min": s.duration_min,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]
