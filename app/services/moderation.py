from app.repository import Repo
from app.models import Post
from app.config import settings
from loguru import logger

repo = Repo()

async def approve_post(post_id: int, admin_id: int):
    await repo.set_post_status(post_id, "approved")
    logger.info(f"Admin {admin_id} approved post {post_id}")
    return True

async def reject_post(post_id: int, admin_id: int, reason: str | None):
    await repo.set_post_status(post_id, "rejected", reason)
    logger.info(f"Admin {admin_id} rejected post {post_id} reason={reason}")
    return True
