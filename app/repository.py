from typing import Iterable, Sequence
from sqlalchemy import select, update, func
from sqlalchemy.orm import joinedload
from app.database import async_sessionmaker
from app import models

class Repo:
    def __init__(self):
        self.Session = async_sessionmaker

    async def get_or_create_user(self, user_id: int, username: str | None):
        async with self.Session() as s:
            u = await s.get(models.User, user_id)
            if not u:
                u = models.User(id=user_id, username=username, is_agreed=False)
                s.add(u)
                await s.commit()
            return u

    async def set_user_agreed(self, user_id: int):
        async with self.Session() as s:
            u = await s.get(models.User, user_id)
            if u:
                u.is_agreed = True
                await s.commit()

    async def add_post(self, post: models.Post, photos: list[tuple[str,str]]):
        async with self.Session() as s:
            s.add(post)
            await s.flush()
            for file_id, phash in photos:
                s.add(models.Photo(post_id=post.id, file_id=file_id, phash=phash))
            # stat
            day = func.strftime('%Y-%m-%d', models.Post.created_at) if s.bind.url.get_backend_name()=="sqlite" else func.to_char(models.Post.created_at, 'YYYY-MM-DD')
            await s.execute(models.StatDaily.__table__.insert().values(day=func.current_date(), created_count=1).prefix_with("ON CONFLICT(day) DO UPDATE SET created_count=stat_daily.created_count+1") if s.bind.url.get_backend_name()=="sqlite" else models.StatDaily.__table__.insert().values(day=func.current_date(), created_count=1).on_conflict_do_update(index_elements=['day'], set_={'created_count': models.StatDaily.created_count + 1}))  # type: ignore
            await s.commit()
            return post.id

    async def find_duplicate_phash(self, phash: str, threshold: int) -> bool:
        # Very basic: exact match fast path; Hamming distance (within SQL) is not trivial — do app-side if needed.
        async with self.Session() as s:
            res = await s.execute(select(models.Photo).where(models.Photo.phash == phash))
            return res.scalar_one_or_none() is not None

    async def get_pending_posts(self) -> Sequence[models.Post]:
        async with self.Session() as s:
            res = await s.execute(select(models.Post).where(models.Post.status=="pending").options(joinedload(models.Post.author)))
            return res.scalars().all()

    async def set_post_status(self, post_id: int, status: str, reason: str | None = None):
        async with self.Session() as s:
            p = await s.get(models.Post, post_id)
            if not p: return
            p.status = status
            if status == "approved":
                p.approved_at = func.now()
            if status == "rejected":
                p.reject_reason = reason
            await s.commit()

    async def get_next_approved_unposted(self) -> models.Post | None:
        async with self.Session() as s:
            res = await s.execute(
                select(models.Post).where(models.Post.status=="approved").order_by(models.Post.created_at).limit(1)
            )
            return res.scalar_one_or_none()

    async def mark_posted(self, post_id: int):
        async with self.Session() as s:
            p = await s.get(models.Post, post_id)
            if p:
                p.status = "posted"
                p.posted_at = func.now()
                await s.commit()

    async def stats_range(self, start_day: str, end_day: str):
        async with self.Session() as s:
            res = await s.execute(select(models.StatDaily).where(models.StatDaily.day.between(start_day, end_day)))
            return res.scalars().all()
