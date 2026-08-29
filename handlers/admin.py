import asyncio
import os
from typing import Optional
from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select, func
from datetime import datetime

from database import async_session_maker
from models import User, Group, Lesson
from config import ADMIN_IDS, logger
from services.api_client import sync_all_courses, LAST_SYNC_INFO, FAILED_DUMP_PATH
from services.cache import (
    warm_up_schedule_cache, 
    USER_CACHE, 
    LESSONS_CACHE, 
    GROUPS_CACHE, 
    TEACHERS_CACHE
)

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
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "• <code>/stats</code> — статистика БД, RAM-кэша и статус API\n"
        "• <code>/sync</code> — принудительная синхронизация\n"
        "• <code>/apidump</code> — скачать дамп последнего ошибочного ответа сайта\n"
        "• <code>/tech Текст сообщения</code> — рассылка оповещения студентам\n"
        "• <code>/logs</code> — скачать файл логов (bot.log)\n"
        "• <code>/syncdate YYYY-MM-DD</code> — синхронизация расписания на указанную дату"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_admin_stats(message: Message):
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

    sync_icon = "✅ Успешно" if LAST_SYNC_INFO["success"] else "❌ Были ошибки"
    sync_time = LAST_SYNC_INFO["timestamp"] or "Еще не запускалась"
    sync_errors = len(LAST_SYNC_INFO["errors"])

    text = (
        "📊 <b>Системная статистика:</b>\n\n"
        "👤 <b>Пользователи:</b>\n"
        f"• Всего в базе: <b>{total_users or 0}</b>\n"
        f"• Зарегистрированы: <b>{users_with_group or 0}</b>\n"
        f"• Утренние уведы (07:45): <b>{active_notifs or 0}</b>\n\n"
        "🗄 <b>База данных & RAM-Кэш:</b>\n"
        f"• Групп: <b>{total_groups or 0}</b> (в RAM: {len(GROUPS_CACHE)})\n"
        f"• Сохранено пар: <b>{total_lessons or 0}</b> (связок недель в RAM: {len(LESSONS_CACHE)})\n"
        f"• Преподавателей в RAM: <b>{len(TEACHERS_CACHE)}</b>\n"
        f"• Кэш юзеров (TTL): <b>{len(USER_CACHE)}</b>\n\n"
        "🌐 <b>Синхронизация с bio.bsu.by:</b>\n"
        f"• Статус: <b>{sync_icon}</b>\n"
        f"• Последний запуск: <code>{sync_time}</code>\n"
        f"• Ошибок при синхронизации: <b>{sync_errors}</b>"
    )

    if not LAST_SYNC_INFO["success"] and LAST_SYNC_INFO["last_error_details"]:
        text += f"\n\n⚠️ <b>Последние ошибки:</b>\n<code>{LAST_SYNC_INFO['last_error_details'][:300]}</code>"

    await message.answer(text)


@router.message(Command("sync"))
async def cmd_force_sync(message: Message, bot: Bot):
    msg = await message.answer("⏳ Синхронизирую все 4 курса...")
    
    try:
        async with async_session_maker() as session:
            res = await sync_all_courses(session, bot=bot)
            await warm_up_schedule_cache(session)

        if res["success"]:
            await msg.edit_text(
                f"✅ <b>Синхронизация успешно завершена!</b>\n\n"
                f"📚 Всего обновлено пар: <b>{res['total_lessons_saved']}</b>\n"
                f"⚡ RAM-кэш успешно прогрет и актуализирован"
            )
        else:
            errors_str = "\n• ".join(res["errors"][:5])
            await msg.edit_text(
                f"⚠️ <b>Синхронизация завершилась с предупреждениями:</b>\n\n"
                f"• {errors_str}\n\n"
                f"<i>(Старые пары в базе были сохранены для предотвращения сбоев)</i>"
            )
    except Exception as e:
        logger.error(f"Критическая ошибка команды /sync: {e}")
        await msg.edit_text(f"❌ <b>Критическая ошибка:</b> <code>{e}</code>")


@router.message(Command("apidump"))
async def cmd_get_api_dump(message: Message):
    if not os.path.exists(FAILED_DUMP_PATH) or os.path.getsize(FAILED_DUMP_PATH) == 0:
        await message.reply("✅ Ошибок парсинга не зафиксировано (файл дампа пуст)")
        return

    try:
        await message.reply_document(
            document=FSInputFile(FAILED_DUMP_PATH, filename="failed_api_response.json"),
            caption="⚠️ Дамп последнего ошибочного ответа от сайта bio.bsu.by"
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить дамп: {e}")


@router.message(Command("tech"))
async def cmd_tech_broadcast(message: Message, command: CommandObject, bot: Bot):
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
            logger.warning(f"Ошибка разметки для {user.telegram_id}: {e}")
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

        await asyncio.sleep(0.04)

    report = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего в базе: <b>{total}</b>\n"
        f"📬 Доставлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали бота (отключены уведы): <b>{blocked_count}</b>\n"
    )
    if bad_request_count > 0:
        report += f"⚠️ Ошибок HTML-разметки: <b>{bad_request_count}</b>\n"
    if other_errors > 0:
        report += f"❌ Прочих сбоев: <b>{other_errors}</b>"

    await status_msg.edit_text(report)


@router.message(Command("logs"))
async def cmd_get_logs(message: Message):
    log_path = "bot.log"
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        await message.reply("Лог-файл пуст или еще не создан")
        return

    try:
        await message.reply_document(
            document=FSInputFile(log_path, filename="bot_logs.txt"), 
            caption="📄 Логи работы бота"
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить логи: {e}")

@router.message(Command("syncdate"))
async def cmd_sync_custom_date(message: Message, command: CommandObject, bot: Bot):
    if not command.args:
        await message.reply("⚠️ Укажите дату: <code>/syncdate 2026-09-01</code>")
        return

    try:
        target_date = datetime.strptime(command.args.strip(), "%Y-%m-%d").date()
    except ValueError:
        await message.reply("❌ Неверный формат даты! Используйте: <code>YYYY-MM-DD</code>")
        return

    msg = await message.answer(f"⏳ Синхронизирую расписание на неделю от <b>{target_date}</b>...")

    async with async_session_maker() as session:
        res = await sync_all_courses(session, target_date=target_date, bot=bot)
        await warm_up_schedule_cache(session)

    if res["total_lessons_saved"] > 0:
        await msg.edit_text(
            f"✅ <b>Успешно!</b> Загружено пар: <b>{res['total_lessons_saved']}</b>\n"
            f"⚡ RAM-кэш обновлен на дату {target_date}."
        )
    else:
        await msg.edit_text(
            f"⚠️ На дату <b>{target_date}</b> на сайте bio.bsu.by нет пар (вернулся пустой список).\n\n"
            f"Ошибки:\n• " + "\n• ".join(res["errors"][:3])
        )