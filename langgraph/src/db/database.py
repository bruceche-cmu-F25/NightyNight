import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Add it to langgraph/.env (e.g. postgresql+asyncpg://user:pass@host/db)."
    )

# Neon / Render / Supabase give postgresql:// URLs; asyncpg needs postgresql+asyncpg://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg rejects all libpq query params (sslmode, channel_binding, etc.)
# Strip every query param; convert sslmode=require → ssl=True via connect_args.
_parsed = urlparse(DATABASE_URL)
_params  = parse_qs(_parsed.query, keep_blank_values=True)
_sslmode = _params.get("sslmode", ["disable"])[0]
_clean_url = urlunparse(_parsed._replace(query=""))
_connect_args = {"ssl": True} if _sslmode in ("require", "verify-ca", "verify-full") else {}

engine = create_async_engine(_clean_url, echo=False, pool_pre_ping=True, connect_args=_connect_args)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
