import asyncio
import os
from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select, func

from database import async_session_maker
from models import User, Group, Lesson
from config import ADMIN_IDS, logger
from services.api_client import sync_all_courses
from typing import Optional

router = Router()


class IsAdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id in ADMIN_IDS


router.message.filter(IsAdminFilter())


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


@router.message(Command("admin"))
@router.message(Command("ahelp"))
async def cmd_admin_help(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "• <code>/stats</code> — статистика пользователей и базы данных\n"
        "• <code>/sync</code> — принудительная синхронизация расписания\n"
        "• <code>/tech Текст сообщения</code> — рассылка важного оповещения всем студентам\n"
        "• <code>/logs</code> — скачать текущий файл логов (bot.log)"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_admin_stats(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    async with async_session_maker() as session:
        total_users = await session.scalar(select(func.count(User.telegram_id)))
        active_notifs = await session.scalar(
            select(func.count(User.telegram_id)).where(User.notifications_enabled == True)
        )
        users_with_group = await session.scalar(
            select(func.count(User.telegram_id)).where(User.group_id.is_not(None))
        )

        total_groups = await session.scalar(select(func.count(Group.id)))
        total_lessons = await session.scalar(select(func.count(Lesson.id)))

    text = (
        "📊 <b>Статистика системы:</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users or 0}</b>\n"
        f"🎓 Прошли регистрацию: <b>{users_with_group or 0}</b>\n"
        f"🔔 Получают утренние уведы: <b>{active_notifs or 0}</b>\n\n"
        f"🏫 Групп в базе: <b>{total_groups or 0}</b>\n"
        f"📚 Сохранено пар (все курсы/недели): <b>{total_lessons or 0}</b>"
    )
    await message.answer(text)


@router.message(Command("tech"))
async def cmd_tech_broadcast(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
        
    broadcast_text = command.args
    if not broadcast_text:
        await message.reply("⚠️ Формат: <code>/tech Текст сообщения</code>")
        return

    async with async_session_maker() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

    total = len(users)
    sent = 0
    blocked_count = 0
    bad_request_count = 0
    other_errors = 0

    status_msg = await message.answer(f"⏳ Начинаю рассылку на {total} пользователей...")

    for user in users:
        try:
            await bot.send_message(
                chat_id=user.telegram_id, 
                text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}"
            )
            sent += 1
        except TelegramForbiddenError:
            blocked_count += 1
            async with async_session_maker() as s:
                db_user = await s.get(User, user.telegram_id)
                if db_user:
                    db_user.notifications_enabled = False
                    await s.commit()
        except TelegramBadRequest as e:
            bad_request_count += 1
            logger.warning(f"Ошибка HTML-разметки для {user.telegram_id}: {e}")
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(
                    chat_id=user.telegram_id, 
                    text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}"
                )
                sent += 1
            except Exception:
                other_errors += 1
        except Exception as e:
            other_errors += 1
            logger.error(f"Ошибка отправки пользователю {user.telegram_id}: {e}")

        await asyncio.sleep(0.05)

    report = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего в базе: <b>{total}</b>\n"
        f"📬 Успешно доставлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали бота (отписаны): <b>{blocked_count}</b>\n"
    )
    if bad_request_count > 0:
        report += f"⚠️ Ошибок HTML-разметки: <b>{bad_request_count}</b>\n"
    if other_errors > 0:
        report += f"❌ Прочих сбоев: <b>{other_errors}</b>"

    await status_msg.edit_text(report)


@router.message(Command("sync"))
async def cmd_force_sync(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    msg = await message.answer("⏳ Синхронизирую все курсы (3 недели) с bio.bsu.by...")
    try:
        async with async_session_maker() as session:
            await sync_all_courses(session)
        await msg.edit_text("✅ Расписание всех курсов успешно обновлено в базе данных!")
    except Exception as e:
        logger.error(f"Ошибка принудительной синхронизации: {e}")
        await msg.edit_text(f"❌ Ошибка синхронизации: <code>{e}</code>")


@router.message(Command("logs"))
async def cmd_get_logs(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    log_path = "bot.log"
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        await message.reply("Лог-файл пуст или еще не создан.")
        return

    try:
        await message.reply_document(
            document=FSInputFile(log_path, filename="bot_logs.txt"), 
            caption="📄 Логи работы бота"
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить логи: {e}")