import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email            = Column(String(320), unique=True, nullable=False)
    hashed_password  = Column(String(200), nullable=True)   # NULL for Google-only accounts
    google_id        = Column(String(100), unique=True, nullable=True)
    display_name     = Column(String(100), nullable=True)

    pref_voice       = Column(String(100), nullable=True)
    pref_audience    = Column(String(100), nullable=True)
    pref_style       = Column(String(100), nullable=True)

    daily_count      = Column(Integer, nullable=False, default=0)
    daily_reset_at   = Column(Date, nullable=False, default=date.today)
    monthly_count    = Column(Integer, nullable=False, default=0)
    monthly_reset_at = Column(Date, nullable=False, default=lambda: date.today().replace(day=1))

    created_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Subscription tier — columns added via manual ALTER TABLE on existing DBs
    plan                   = Column(String(32),  nullable=False, default="free")
    subscription_status    = Column(String(32),  nullable=False, default="inactive")
    premium_until          = Column(DateTime,    nullable=True)   # reserved for trial/gift flows
    stripe_customer_id     = Column(String(128), nullable=True)
    stripe_subscription_id = Column(String(128), nullable=True)


def user_is_premium(user: User) -> bool:
    """Backend entitlement check — always called server-side, never trusted from client."""
    return (
        user.plan == "premium"
        and user.subscription_status in ("active", "trialing")
    )


class Story(Base):
    __tablename__ = "stories"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic        = Column(Text, nullable=False)
    story_text   = Column(Text, nullable=False)
    audio_url    = Column(String(500), nullable=True)
    duration_min = Column(Integer, nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_stories_user_created", Story.user_id, Story.created_at)
