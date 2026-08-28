import asyncio
import os
from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile
from sqlalchemy import select

from database import async_session_maker
from models import User
from config import ADMIN_IDS, logger
from services.api_client import sync_all_courses

router = Router()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@router.message(Command("tech"))
async def cmd_tech_broadcast(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id):
        return
        
    broadcast_text = command.args
    if not broadcast_text:
        await message.reply("⚠️ Формат: <code>/tech Текст сообщения</code>")
        return

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    total, sent, blocked = len(user_ids), 0, 0
    status_msg = await message.answer(f"⏳ Начинаю рассылку на {total} пользователей...")

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}")
            sent += 1
        except Exception:
            blocked += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего: <b>{total}</b>\n"
        f"📬 Доставлено: <b>{sent}</b>\n"
        f"🚫 Ошибок: <b>{blocked}</b>"
    )

@router.message(Command("sync"))
async def cmd_force_sync(message: Message):
    if not is_admin(message.from_user.id):
        return

    msg = await message.answer("⏳ Синхронизирую все 4 курса с bio.bsu.by...")
    async with async_session_maker() as session:
        await sync_all_courses(session)
    await msg.edit_text("✅ Расписание всех курсов успешно обновлено в базе данных!")

@router.message(Command("logs"))
async def cmd_get_logs(message: Message):
    if not is_admin(message.from_user.id):
        return

    log_path = "bot.log"
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        await message.reply("Лог-файл пуст")
        return

    await message.reply_document(document=FSInputFile(log_path, filename="bot_logs.txt"), caption="📄 Логи бота")