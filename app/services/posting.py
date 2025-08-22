from aiogram import Bot
from aiogram.types import InputMediaPhoto
from app.repository import Repo
from app.config import settings
from loguru import logger

repo = Repo()

def render_post_caption(p) -> str:
    parts = [f"#{p.category} • {p.district}", f"*{p.title}*", p.description, f"_Контакти:_ {p.contacts}"]
    return "\n".join(parts)

async def post_next(bot: Bot, target_chat_id: int) -> bool:
    post = await repo.get_next_approved_unposted()
    if not post:
        return False
    # fetch photos
    # naive fetch: not loading photos table separately; for brevity, reselect
    from sqlalchemy import select
    from app.database import async_sessionmaker
    from app import models
    async with async_sessionmaker() as s:
        res = await s.execute(select(models.Photo).where(models.Photo.post_id == post.id))
        photos = res.scalars().all()

    if photos:
        media = [InputMediaPhoto(media=ph.file_id) for ph in photos[:10]]
        await bot.send_media_group(target_chat_id, media=media)
    await bot.send_message(target_chat_id, render_post_caption(post), parse_mode="Markdown")
    await repo.mark_posted(post.id)
    logger.info(f"Posted post {post.id} to {target_chat_id}")
    return True
