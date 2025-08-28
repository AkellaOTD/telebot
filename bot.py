import os
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from fastapi import FastAPI
import uvicorn

# -------------------
# Ініціалізація
# -------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATORS_CHAT_ID = int(os.getenv("MODERATORS_CHAT_ID"))
PUBLISH_CHAT_ID = int(os.getenv("PUBLISH_CHAT_ID"))

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())
app = FastAPI()

# -------------------
# База даних
# -------------------
conn = sqlite3.connect("ads.db", check_same_thread=False)
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
    is_published BOOLEAN DEFAULT 0,
    is_rejected BOOLEAN DEFAULT 0,
    rejection_reason TEXT,
    moder_message_id INTEGER
)
""")
conn.commit()

# -------------------
# Стан машини
# -------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()


class RejectAd(StatesGroup):
    waiting_reason = State()


# -------------------
# Клавіатура для модерації
# -------------------
def get_moder_keyboard(ad_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опублікувати", callback_data=f"publish_{ad_id}"),
        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{ad_id}")
    )
    return kb


# -------------------
# Старт бота
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
    await message.answer("📸 Надішліть до 20 фото (або /skip щоб пропустити):")
    await AdForm.next()


@dp.message_handler(lambda m: m.text == "/skip", state=AdForm.photos)
async def skip_photos(message: types.Message, state: FSMContext):
    await state.update_data(photos="")
    await message.answer("📞 Вкажіть контакти (до 200 символів):")
    await AdForm.next()


@dp.message_handler(content_types=types.ContentTypes.PHOTO, state=AdForm.photos)
async def ad_photos(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", "").split(",") if data.get("photos") else []
    if len(photos) >= 20:
        return await message.answer("❌ Максимум 20 фото")
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=",".join(photos))
    await message.answer("Фото додано ✅. Можете надіслати ще або /skip")


@dp.message_handler(state=AdForm.contacts)
async def ad_contacts(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        return await message.answer("❌ Контакти занадто довгі, максимум 200 символів")

    await state.update_data(contacts=message.text)
    data = await state.get_data()

    # Зберігаємо в БД
    cursor.execute("""
        INSERT INTO ads (user_id, category, district, title, description, photos, contacts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        data["category"],
        data["district"],
        data["title"],
        data["description"],
        data.get("photos", ""),
        data["contacts"]
    ))
    conn.commit()
    ad_id = cursor.lastrowid

    # Формуємо текст
    ad_text = (
        f"📢 НОВЕ ОГОЛОШЕННЯ #{ad_id}\n\n"
        f"🔹 Категорія: {data['category']}\n"
        f"📍 Район: {data['district']}\n"
        f"🏷 Заголовок: {data['title']}\n"
        f"📝 Опис: {data['description']}\n"
        f"📞 Контакти: {data['contacts']}\n"
    )

    # Відправляємо в групу модераторів
    if data.get("photos"):
        photos = data["photos"].split(",")
        media = [InputMediaPhoto(media=p) for p in photos]
        media[0].caption = ad_text
        msg = await bot.send_media_group(MODERATORS_CHAT_ID, media=media)
        # кнопки прикріплюємо окремо
        sent = await bot.send_message(MODERATORS_CHAT_ID, f"⬆️ Оголошення #{ad_id}", reply_markup=get_moder_keyboard(ad_id))
        moder_message_id = sent.message_id
    else:
        msg = await bot.send_message(MODERATORS_CHAT_ID, ad_text, reply_markup=get_moder_keyboard(ad_id))
        moder_message_id = msg.message_id

    # Зберігаємо message_id для видалення
    cursor.execute("UPDATE ads SET moder_message_id=? WHERE id=?", (moder_message_id, ad_id))
    conn.commit()

    await message.answer("✅ Ваше оголошення надіслано на модерацію")
    await state.finish()


# -------------------
# Модерація: Публікація
# -------------------
@dp.callback_query_handler(lambda c: c.data.startswith("publish_"))
async def process_publish(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])

    cursor.execute("UPDATE ads SET is_published=1 WHERE id=?", (ad_id,))
    conn.commit()

    cursor.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
    ad = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    ad_dict = dict(zip(columns, ad))

    ad_text = (
        f"📢 ОГОЛОШЕННЯ\n\n"
        f"🔹 Категорія: {ad_dict['category']}\n"
        f"📍 Район: {ad_dict['district']}\n"
        f"🏷 Заголовок: {ad_dict['title']}\n"
        f"📝 Опис: {ad_dict['description']}\n"
        f"📞 Контакти: {ad_dict['contacts']}\n"
    )

    if ad_dict["photos"]:
        photos = ad_dict["photos"].split(",")
        media = [InputMediaPhoto(media=p) for p in photos]
        media[0].caption = ad_text
        await bot.send_media_group(PUBLISH_CHAT_ID, media=media)
    else:
        await bot.send_message(PUBLISH_CHAT_ID, ad_text)

    try:
        await bot.delete_message(MODERATORS_CHAT_ID, ad_dict["moder_message_id"])
    except:
        pass

    await callback_query.answer("Оголошення опубліковано ✅")


# -------------------
# Модерація: Відхилення
# -------------------
@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def process_reject(callback_query: types.CallbackQuery, state: FSMContext):
    ad_id = int(callback_query.data.split("_")[1])
    await state.update_data(ad_id=ad_id)
    await RejectAd.waiting_reason.set()
    await bot.send_message(callback_query.message.chat.id, f"Введіть причину відхилення оголошення #{ad_id}:")
    await callback_query.answer("Очікую причину...")


@dp.message_handler(state=RejectAd.waiting_reason, content_types=types.ContentTypes.TEXT)
async def reject_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ad_id = data["ad_id"]
    reason = message.text.strip()

    cursor.execute("UPDATE ads SET is_rejected=1, rejection_reason=? WHERE id=?", (reason, ad_id))
    conn.commit()

    cursor.execute("SELECT user_id, moder_message_id FROM ads WHERE id=?", (ad_id,))
    row = cursor.fetchone()
    user_id, moder_message_id = row

    await bot.send_message(user_id, f"❌ Ваше оголошення #{ad_id} відхилено.\nПричина: {reason}")

    try:
        await bot.delete_message(MODERATORS_CHAT_ID, moder_message_id)
    except:
        pass

    await message.answer(f"Причину відхилення #{ad_id} збережено ✅")
    await state.finish()


# -------------------
# FastAPI endpoint
# -------------------
@app.get("/ads")
async def get_ads():
    cursor.execute("SELECT * FROM ads")
    ads = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return {"ads": [dict(zip(columns, ad)) for ad in ads]}


# -------------------
# Запуск
# -------------------
if __name__ == "__main__":
    import asyncio
    from aiogram import executor

    loop = asyncio.get_event_loop()

    async def start_bot():
        executor.start_polling(dp, skip_updates=True)

    async def start_api():
        config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
        server = uvicorn.Server(config)
        await server.serve()

    loop.create_task(start_bot())
    loop.run_until_complete(start_api())