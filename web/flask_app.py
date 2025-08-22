from flask import Flask, request, abort
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiogram.webhook import WebhookRequestHandler
from app.config import settings
from app.database import init_models
from bot.routers import start_router, add_router, admin_router, misc_router
import asyncio

app = Flask(__name__)

bot = Bot(settings.BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
dp.include_router(start_router)
dp.include_router(add_router)
dp.include_router(admin_router)
dp.include_router(misc_router)

@app.before_first_request
def setup():
    loop = asyncio.get_event_loop()
    loop.create_task(init_models())

@app.get("/health")
def health():
    return {"ok": True}

@app.post(f"/webhook/{settings.WEBHOOK_SECRET or 'secret'}")
def webhook():
    # Using aiogram native webhook adapter is easier with aiohttp; here we simply forward raw updates
    from aiogram.types import Update
    if request.headers.get("content-type") != "application/json":
        abort(400)
    update = Update.model_validate_json(request.data.decode("utf-8"))
    asyncio.get_event_loop().create_task(dp.feed_update(bot, update))
    return {"ok": True}
