import os
import asyncio
import threading
from flask import Flask, request, abort
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # наприклад: https://yourdomain.com
PORT = int(os.getenv("PORT", 8000))

app = Flask(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# створюємо власний event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


# === Приклад простого хендлера ===
@dp.message()
async def echo_handler(message):
    await message.answer(f"Echo: {message.text}")


# === Flask webhook endpoint (синхронний) ===
@app.post(WEBHOOK_PATH)
def webhook():
    if not request.is_json:
        abort(400)
    data = request.get_json(force=True)
    update = Update.model_validate(data)
    # відправляємо апдейт у Dispatcher через наш loop
    asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), loop)
    return {"ok": True}


# === Startup / Shutdown ===
async def on_startup():
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
    # реєструємо webhook при старті
    loop.run_until_complete(on_startup())

    # запускаємо Flask у окремому потоці
    threading.Thread(target=run_flask, daemon=True).start()

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(on_shutdown())