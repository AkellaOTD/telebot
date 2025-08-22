from sqlalchemy import BigInteger, String, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime, timezone
from app.database import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(32))
    is_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # chat id
    title: Mapped[str | None] = mapped_column(String(255))
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False)
    cron: Mapped[str | None] = mapped_column(String(64))  # e.g., '*/15 * * * *'
    interval_sec: Mapped[int | None] = mapped_column(Integer)  # alternative to cron

class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(50))
    district: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    contacts: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|posted
    reject_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped["User"] = relationship()

class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    file_id: Mapped[str] = mapped_column(String(200))
    phash: Mapped[str] = mapped_column(String(32))

    __table_args__ = (UniqueConstraint("phash", name="uq_photo_phash"),)

class AdminAction(Base):
    __tablename__ = "admin_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(50))
    post_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Blacklist(Base):
    __tablename__ = "blacklist"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class StatDaily(Base):
    __tablename__ = "stat_daily"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    posted_count: Mapped[int] = mapped_column(Integer, default=0)
