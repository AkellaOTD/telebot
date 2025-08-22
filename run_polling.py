import asyncio
from aiogram import Bot, Dispatcher
from app.config import settings
from app.database import init_models
from bot.routers import start_router, add_router, admin_router, misc_router
from bot.middlewares import RateLimitMiddleware

async def main():
    await init_models()
    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.message.middleware(RateLimitMiddleware())
    dp.include_router(start_router)
    dp.include_router(add_router)
    dp.include_router(admin_router)
    dp.include_router(misc_router)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
