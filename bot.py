import os
import sqlite3
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv

# -------------------
# ENV
# -------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # наприклад: https://your-app.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 10000))

MODERATORS_CHAT_ID = int(os.getenv("MODERATORS_CHAT_ID", 0))
PUBLISH_CHAT_ID = int(os.getenv("PUBLISH_CHAT_ID", 0))

# -------------------
# Ініціалізація
# -------------------
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# -------------------
# База даних
# -------------------
conn = sqlite3.connect("ads.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    district TEXT,
    title TEXT,
    description TEXT,
    photos TEXT,
    contacts TEXT,
    is_published INTEGER DEFAULT 0,
    is_rejected INTEGER DEFAULT 0,
    rejection_reason TEXT,
    moder_message_id INTEGER
)
""")
conn.commit()

# -------------------
# FSM
# -------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

# -------------------
# /start
# -------------------
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Вітаю! Давайте створимо ваше оголошення.\nНапишіть категорію:")
    await AdForm.category.set()

# -------------------
# Створення оголошення
# -------------------
@dp.message_handler(state=AdForm.category)
async def ad_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📍 Вкажіть район:")
    await AdForm.next()

@dp.message_handler(state=AdForm.district)
async def ad_district(message: types.Message, state: FSMContext):
    await state.update_data(district=message.text)
    await message.answer("🏷 Введіть заголовок (до 200 символів):")
    await AdForm.next()

@dp.message_handler(state=AdForm.title)
async def ad_title(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        return await message.answer("❌ Заголовок занадто довгий, максимум 200 символів")
    await state.update_data(title=message.text)
    await message.answer("📝 Введіть опис (до 2000 символів):")
    await AdForm.next()

@dp.message_handler(state=AdForm.description)
async def ad_description(message: types.Message, state: FSMContext):
    if len(message.text) > 2000:
        return await message.answer("❌ Опис занадто довгий, максимум 2000 символів")
    await state.update_data(description=message.text)
    await message.answer("📞 Вкажіть контакти (до 200 символів):")
    await AdForm.next()

@dp.message_handler(state=AdForm.contacts)
async def ad_contacts(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        return await message.answer("❌ Контакти занадто довгі, максимум 200 символів")

    await state.update_data(contacts=message.text)
    data = await state.get_data()

    # Зберігаємо в БД
    cursor.execute("""
        INSERT INTO ads (user_id, category, district, title, description, contacts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        data["category"],
        data["district"],
        data["title"],
        data["description"],
        data["contacts"]
    ))
    conn.commit()
    ad_id = cursor.lastrowid

    await message.answer("✅ Ваше оголошення збережено і надіслано на модерацію!")
    await state.finish()

    # -------------------
    # Надсилаємо в групу модераторів
    # -------------------
    ad_text = (
        f"📢 НОВЕ ОГОЛОШЕННЯ #{ad_id}\n\n"
        f"🔹 Категорія: {data['category']}\n"
        f"📍 Район: {data['district']}\n"
        f"🏷 Заголовок: {data['title']}\n"
        f"📝 Опис: {data['description']}\n"
        f"📞 Контакти: {data['contacts']}\n"
    )

    moder_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"publish_{ad_id}"),
            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{ad_id}")
        ]
    ])

    msg = await bot.send_message(
        chat_id=MODERATORS_CHAT_ID,
        text=ad_text,
        reply_markup=moder_kb
    )

    cursor.execute("UPDATE ads SET moder_message_id=? WHERE id=?", (msg.message_id, ad_id))
    conn.commit()

# -------------------
# Webhook startup/shutdown
# -------------------
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown(dp):
    logging.warning("Shutting down..")
    await bot.delete_webhook()

if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )