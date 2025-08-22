import time
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
from app.config import settings

class RateLimitMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.bucket: Dict[int, list[float]] = defaultdict(list)

    async def __call__(self, handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]):
        now = time.time()
        uid = event.from_user.id if event.from_user else 0
        window = 60.0
        self.bucket[uid] = [t for t in self.bucket[uid] if now - t < window]
        if len(self.bucket[uid]) >= settings.RATE_LIMIT_PER_MINUTE:
            return
        self.bucket[uid].append(now)
        return await handler(event, data)
