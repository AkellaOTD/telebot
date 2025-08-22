import os
import asyncio
from flask import Flask, request, abort
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://yourdomain.com/webhook

app = Flask(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()


# 👉 тут реєструєш свої хендлери
@dp.message()
async def echo_handler(message):
    await message.answer(f"Echo: {message.text}")


@app.post(WEBHOOK_PATH)
async def webhook():
    if not request.is_json:
        abort(400)
    data = request.get_json(force=True)
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


async def on_startup():
    # встановлюємо webhook у Telegram
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)


async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()


if __name__ == "__main__":
    import threading

    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup())

    # Flask працює в окремому потоці
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    ).start()

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(on_shutdown())