import os
import asyncio
import logging
from datetime import datetime

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import TelegramRetryAfter, TelegramForbiddenError

from main import bot, cursor, conn   # імпортуємо з твого основного файлу

# Налаштовуємо логування
logging.basicConfig(level=logging.INFO)

# Інтервал у секундах
AUTOPOST_INTERVAL = int(os.getenv("AUTOPOST_INTERVAL", 3600))

PUBLISH_CHAT_ID = int(os.getenv("PUBLISH_CHAT_ID"))

async def autopost():
    while True:
        try:
            # беремо одне нове оголошення
            cursor.execute("""
                SELECT id, user_id, username, first_name, category, district, title, description, photos, contacts
                FROM ads
                WHERE is_published=0 AND is_rejected=0
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
                        cursor.execute("UPDATE ads SET is_published=1 WHERE id=?", (ad_id,))
                        conn.commit()
                        logging.info(f"✅ Автопостинг: оголошення #{ad_id} опубліковане")

                    except TelegramRetryAfter as e:
                        logging.warning(f"Flood control: sleep {e.timeout}s")
                        await asyncio.sleep(e.timeout)
                    except TelegramForbiddenError:
                        logging.error("❌ Бот заблокований у каналі/чаті")

            await asyncio.sleep(AUTOPOST_INTERVAL)

        except Exception as e:
            logging.exception(f"Помилка в автопостингу: {e}")
            await asyncio.sleep(AUTOPOST_INTERVAL)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(autopost())