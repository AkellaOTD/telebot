from aiogram import Router, F
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, PhotoSize
from app.repository import Repo
from app.models import Post
from app.config import settings
from app.utils.phash import compute_phash_from_bytes
from app.services.spam import has_bad_words

router = Router()
repo = Repo()

class AddPost(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

@router.message(F.text == "/add")
async def start_add(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddPost.category)
    await m.answer("Категорія (напр., "знайдено", "загублено", "пристроюється"):")

@router.message(AddPost.category, F.text.len() > 0)
async def set_category(m: Message, state: FSMContext):
    await state.update_data(category=m.text.strip()[:50])
    await state.set_state(AddPost.district)
    await m.answer("Район/місто:")

@router.message(AddPost.district, F.text.len() > 0)
async def set_district(m: Message, state: FSMContext):
    await state.update_data(district=m.text.strip()[:100])
    await state.set_state(AddPost.title)
    await m.answer("Заголовок (≤200):")

@router.message(AddPost.title, F.text.len() > 0)
async def set_title(m: Message, state: FSMContext):
    txt = m.text.strip()
    if len(txt) > 200:
        return await m.answer("Занадто довгий заголовок (≤200). Введіть знову.")
    if has_bad_words(txt):
        return await m.answer("Заборонені слова у заголовку.")
    await state.update_data(title=txt)
    await state.set_state(AddPost.description)
    await m.answer("Опис (≤2000):")

@router.message(AddPost.description, F.text.len() > 0)
async def set_description(m: Message, state: FSMContext):
    txt = m.text.strip()
    if len(txt) > 2000:
        return await m.answer("Занадто довгий опис (≤2000).")
    if has_bad_words(txt):
        return await m.answer("Заборонені слова в описі.")
    await state.update_data(description=txt)
    await state.set_state(AddPost.photos)
    await m.answer(f"Надішліть фото (до {settings.MAX_PHOTOS}). Коли достатньо — надішліть 'далі'.")

@router.message(AddPost.photos, F.photo)
async def add_photo(m: Message, state: FSMContext):
    photos = (await state.get_data()).get("photos", [])
    if len(photos) >= settings.MAX_PHOTOS:
        return await m.answer("Досягнуто ліміт фото. Напишіть 'далі'.")
    best: PhotoSize = m.photo[-1]
    file = await m.bot.get_file(best.file_id)
    data = await m.bot.download_file(file.file_path)
    phash = compute_phash_from_bytes(data.read())
    # quick duplicate check (exact hash)
    if await repo.find_duplicate_phash(phash, settings.PHASH_HAMMING_THRESHOLD):
        return await m.answer("Схоже, таке фото вже було в базі. Надішліть інше.")
    photos.append((best.file_id, phash))
    await state.update_data(photos=photos)
    await m.answer(f"Фото додано ({len(photos)}/{settings.MAX_PHOTOS}). Надішліть ще або напишіть 'далі'.")

@router.message(AddPost.photos, F.text.casefold() == "далі")
async def photos_done(m: Message, state: FSMContext):
    await state.set_state(AddPost.contacts)
    await m.answer("Контакти (≤200):")

@router.message(AddPost.contacts, F.text.len() > 0)
async def set_contacts(m: Message, state: FSMContext):
    txt = m.text.strip()
    if len(txt) > 200:
        return await m.answer("Занадто довгі контакти (≤200).")
    if has_bad_words(txt):
        return await m.answer("Заборонені слова в контактах.")
    data = await state.update_data(contacts=txt)
    # persist post
    post = Post(
        author_id=m.from_user.id,
        category=data["category"],
        district=data["district"],
        title=data["title"],
        description=data["description"],
        contacts=data["contacts"],
    )
    post_id = await repo.add_post(post, data.get("photos", []))
    await state.clear()
    # send to admin group for moderation
    await m.answer(f"Оголошення #{post_id} відправлено на модерацію. Дякуємо!")
    from bot.keyboards import moderation_kb
    await m.bot.send_message(chat_id=int(__import__('app.config').config.settings.ADMIN_GROUP_ID),
                             text=f"""Нове оголошення #{post_id}
Категорія: {post.category}
Район: {post.district}
Заголовок: {post.title}
Опис: {post.description[:500]}...
Контакти: {post.contacts}
Автор: @{m.from_user.username or m.from_user.id}
""", reply_markup=moderation_kb(post_id))
