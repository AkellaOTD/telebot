import os
import logging
import asyncio
import sqlite3
from dotenv import load_dotenv
from pathlib import Path
from aiogram import Bot, types
from aiogram.types import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("BOT_TOKEN")
PUBLISH_CHAT_ID = int(os.getenv("PUBLISH_CHAT_ID"))
DB_PATH = "bot.db"

bot = Bot(token=TOKEN, parse_mode="HTML")

logging.basicConfig(level=logging.INFO)

async def autopost_once():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # беремо одне нове оголошення
    cursor.execute("""
        SELECT id, user_id, username, first_name, category, district, title, description, photos, contacts
        FROM ads
        WHERE is_queued=1 AND is_published=0 AND is_rejected=0
        ORDER BY created_at ASC
        LIMIT 1
    """)
    ad = cursor.fetchone()

    if ad:
        ad_id, user_id, username, first_name, category, district, title, description, photos, contacts = ad

        # шукаємо гілку для цієї категорії
        cursor.execute(
            "SELECT thread_id FROM threads WHERE chat_id=? AND title=?",
            (PUBLISH_CHAT_ID, category)
        )
        row = cursor.fetchone()

        if not row:
            logging.warning(f"❌ Категорія '{category}' не привʼязана до публічного чату")
        else:
            thread_id = row[0]

            pub_text = (
                f"📢 ОГОЛОШЕННЯ #{ad_id}\n\n"
                f"👤 Користувач: {first_name or ''} (@{username})\n\n"
                f"🔹 Категорія: {category}\n"
                f"📍 Район: {district}\n"
                f"🏷 Заголовок: {title}\n"
                f"📝 Опис: {description}\n"
                f"📞 Контакти: {contacts}\n"
            )

            pub_kb = InlineKeyboardMarkup()
            if username:
                pub_kb.add(InlineKeyboardButton(f"👤 @{username}", url=f"https://t.me/{username}"))
            else:
                pub_kb.add(InlineKeyboardButton("👤 Профіль", url=f"tg://user?id={user_id}"))
            pub_kb.add(InlineKeyboardButton("🔗 Поділитися", switch_inline_query=str(ad_id)))

            try:
                if photos:
                    photos = photos.split(",")
                    if len(photos) == 1:
                        await bot.send_photo(
                            chat_id=PUBLISH_CHAT_ID,
                            message_thread_id=thread_id,
                            photo=photos[0],
                            caption=pub_text,
                            reply_markup=pub_kb
                        )
                    else:
                        media = [types.InputMediaPhoto(p) for p in photos[:10]]
                        await bot.send_media_group(chat_id=PUBLISH_CHAT_ID, message_thread_id=thread_id, media=media)
                        await bot.send_message(
                            chat_id=PUBLISH_CHAT_ID,
                            message_thread_id=thread_id,
                            text=pub_text,
                            reply_markup=pub_kb
                        )
                else:
                    await bot.send_message(
                        chat_id=PUBLISH_CHAT_ID,
                        message_thread_id=thread_id,
                        text=pub_text,
                        reply_markup=pub_kb
                    )

                # позначаємо як опубліковане
                cursor.execute("UPDATE ads SET is_published=1, is_queued=0 WHERE id=?", (ad_id,))
                conn.commit()
                kb = ReplyKeyboardMarkup(resize_keyboard=True).add("📢 Подати оголошення","📋 Мої оголошення")
                bot.send_message(user_id, "✅ Ваше оголошення успішно опубліковане!", reply_markup=kb)
            finally:
                conn.close()

if __name__ == "__main__":
    asyncio.run(autopost_once())