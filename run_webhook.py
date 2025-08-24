import os
import asyncio
import threading
from flask import Flask, request, abort
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from dotenv import load_dotenv

import aiosqlite
from aiogram import F
from aiogram.types import Message

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # наприклад: https://yourdomain.com
PORT = int(os.getenv("PORT", 8000))

DB_PATH = "database.db"

app = Flask(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# створюємо власний event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


# === Ініціалізація БД ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            chat_title TEXT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            text TEXT,
            photo_id TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()


# === Хендлер для збереження постів у групах ===
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def save_group_post(message: Message):
    text = message.text or ""
    photo_id = None

    if message.photo:
        photo_id = message.photo[-1].file_id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO posts (chat_id, chat_title, user_id, username, full_name, text, photo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.chat.id,
                message.chat.title,
                message.from_user.id if message.from_user else None,
                message.from_user.username if message.from_user else None,
                message.from_user.full_name if message.from_user else None,
                text,
                photo_id,
            ),
        )
        await db.commit()

    print(f"✅ Saved post from {message.from_user.full_name}: {text[:30]}...")


# === Flask webhook endpoint (синхронний) ===
@app.post(WEBHOOK_PATH)
def webhook():
    if not request.is_json:
        abort(400)
    data = request.get_json(force=True)
    update = Update.model_validate(data)
    asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), loop)
    return {"ok": True}


# === Startup / Shutdown ===
async def on_startup():
    await init_db()
    if WEBHOOK_URL:
        full_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
        await bot.set_webhook(full_url)
        print(f"✅ Webhook встановлено: {full_url}")


async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()
    print("🛑 Webhook видалено, сесія закрита.")


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    # запуск ініціалізації + webhook
    loop.run_until_complete(on_startup())

    # запускаємо Flask у окремому потоці
    threading.Thread(target=run_flask, daemon=True).start()

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(on_shutdown())