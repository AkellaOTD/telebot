from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from bot.filters import AdminFilter
from app.services.moderation import approve_post, reject_post
from app.repository import Repo
from app.config import settings
from app.utils.stats import day_range

router = Router()
router.message.filter(AdminFilter())
repo = Repo()

@router.callback_query(F.data.startswith("mod:"))
async def moderation(cb: CallbackQuery):
    parts = cb.data.split(":")
    action = parts[1]
    post_id = int(parts[2])
    if action == "approve":
        await approve_post(post_id, cb.from_user.id)
        await cb.message.edit_text(cb.message.text + "\n\n✅ Approved")
        await cb.bot.send_message(post_id, "")  # placeholder to keep token warm
    elif action == "reject":
        await cb.message.answer("Надішліть причину відхилення у відповідь на це повідомлення.")
        await cb.message.reply_markup  # no-op
    await cb.answer()

@router.message(F.reply_to_message, F.text, AdminFilter())
async def reject_with_reason(m: Message):
    # crude way: if replying to a moderation card
    if "Нове оголошення #" in (m.reply_to_message.text or ""):
        import re
        mobj = re.search(r"#(\d+)", m.reply_to_message.text)
        if mobj:
            post_id = int(mobj.group(1))
            await reject_post(post_id, m.from_user.id, m.text.strip()[:200])
            await m.reply(f"Відхилено #{post_id}: {m.text.strip()[:200]}")

@router.message(F.text.in_({"/stats_day","/stats_week","/stats_month"}))
async def stats_cmd(m: Message):
    period = m.text.split("_")[1]
    start, end = day_range(period)
    rows = await repo.stats_range(start, end)
    created = sum(r.created_count for r in rows)
    approved = sum(r.approved_count for r in rows) if hasattr(rows[0], 'approved_count') if rows else 0
    posted = sum(r.posted_count for r in rows) if hasattr(rows[0], 'posted_count') if rows else 0
    await m.answer(f"Статистика за {period}: створено={created}, схвалено={approved}, опубліковано={posted}")
