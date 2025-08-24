import os
import sqlite3
from aiogram import types
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# -------------------------------
# 🔹 Налаштування
# -------------------------------
API_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://mybot.onrender.com")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8000))  # Render дає PORT автоматично

# -------------------------------
# 🔹 База даних (SQLite)
# -------------------------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    accepted_rules BOOLEAN
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    district TEXT,
    title TEXT,
    description TEXT,
    photos TEXT,
    contacts TEXT
)
""")
conn.commit()

# -------------------------------
# 🔹 FSM стани
# -------------------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

# -------------------------------
# 🔹 Ініціалізація
# -------------------------------
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
app = FastAPI()

# -------------------------------
# 🔹 /start команда
# -------------------------------
@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[0]:
        await message.answer("✅ Ви вже погодились із правилами!\nНатисніть /create щоб створити оголошення.")
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton("✅ Погоджуюсь"), KeyboardButton("❌ Не погоджуюсь"))
        await message.answer("📜 Правила:\n1. ...\n2. ...\n\nВи погоджуєтесь?", reply_markup=kb)

# -------------------------------
# 🔹 Згода/відмова
# -------------------------------
@dp.message_handler(lambda m: m.text in ["✅ Погоджуюсь", "❌ Не погоджуюсь"])
async def process_rules(message: types.Message):
    if message.text == "✅ Погоджуюсь":
        cursor.execute("INSERT OR REPLACE INTO users (user_id, accepted_rules) VALUES (?, ?)", (message.from_user.id, True))
        conn.commit()
        await message.answer("Дякуємо! ✅ Тепер натисніть /create щоб додати оголошення.", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("👋 До побачення!", reply_markup=ReplyKeyboardRemove())
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)

# -------------------------------
# 🔹 Ендпоінти FastAPI
# -------------------------------
@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    data = await request.json()
    update = types.Update.to_object(data)   # ✅ правильне створення Update
    await dp.process_update(update)
    return {"ok": True}

@app.get("/users")
async def get_users():
    cursor.execute("SELECT user_id, accepted_rules FROM users")
    rows = cursor.fetchall()
    return JSONResponse([{"user_id": r[0], "accepted_rules": bool(r[1])} for r in rows])

@app.get("/ads")
async def get_ads():
    cursor.execute("SELECT id, user_id, category, district, title, description, photos, contacts FROM ads")
    rows = cursor.fetchall()
    ads = [
        {
            "id": r[0],
            "user_id": r[1],
            "category": r[2],
            "district": r[3],
            "title": r[4],
            "description": r[5],
            "photos": r[6].split(",") if r[6] else [],
            "contacts": r[7]
        }
        for r in rows
    ]
    return JSONResponse(ads)

# -------------------------------
# 🔹 Хуки для Render
# -------------------------------
@app.on_event("startup")
async def on_startup():
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()