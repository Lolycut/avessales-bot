import asyncio
import os
from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select, func

from database import async_session_maker
from models import User, Group, Lesson, Week, Chat
from services.schedule_cache import schedule_cache
from config import ADMIN_IDS, logger
from services.api_client import sync_all_courses, LAST_SYNC_INFO

router = Router()


class IsAdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id in ADMIN_IDS


router.message.filter(IsAdminFilter())


@router.message(Command("admin"))
@router.message(Command("ahelp"))
async def cmd_admin_help(message: Message):
    text = (
        "👑 <b>Панель администратора AvesSales</b>\n\n"
        "• <code>/stats</code> — системная статистика, БД и In-Memory кэш\n"
        "• <code>/allstats</code> — срез студентов и бесед по каждому курсу и группе\n"
        "• <code>/sync</code> — принудительная синхронизация с bio.bsu.by\n"
        "• <code>/tech Текст</code> — рассылка оповещения студентам\n"
        "• <code>/logs</code> — скачать файл логов (bot.log)"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_admin_stats(message: Message):
    async with async_session_maker() as session:
        # Пользователи
        total_users = await session.scalar(select(func.count(User.telegram_id)))
        active_notifs = await session.scalar(
            select(func.count(User.telegram_id)).where(User.notifications_enabled == True)
        )
        users_with_group = await session.scalar(select(func.count(User.telegram_id)).where(User.group_id.is_not(None)))

        # Беседы (группы)
        total_chats = await session.scalar(select(func.count(Chat.chat_id)))
        active_chats = await session.scalar(select(func.count(Chat.chat_id)).where(Chat.is_active == True))
        chats_with_notifs = await session.scalar(
            select(func.count(Chat.chat_id)).where(Chat.notifications_enabled == True)
        )
        chats_with_group = await session.scalar(select(func.count(Chat.chat_id)).where(Chat.group_id.is_not(None)))

        # БД
        total_groups = await session.scalar(select(func.count(Group.id)))
        total_lessons = await session.scalar(select(func.count(Lesson.id)))
        total_weeks = await session.scalar(select(func.count(Week.id)))

    # In-Memory кэш
    cache_info = schedule_cache.get_cache_stats()
    cache_ready_str = "✅ Готов к работе" if cache_info["is_ready"] else "❌ Не инициализирован"

    sync_time = LAST_SYNC_INFO.get("timestamp") or "Еще не запускалась"
    sync_count = LAST_SYNC_INFO.get("total_lessons_saved", 0)

    text = (
        "📊 <b>Системная статистика и состояние:</b>\n\n"
        "👤 <b>Студенты (ЛС):</b>\n"
        f"• Всего пользователей: <b>{total_users or 0}</b>\n"
        f"• Завершили регистрацию: <b>{users_with_group or 0}</b>\n"
        f"• Утренние уведомления (07:45): <b>{active_notifs or 0}</b>\n\n"
        "👥 <b>Беседы / Групповые чаты:</b>\n"
        f"• Всего подключено бесед: <b>{total_chats or 0}</b>\n"
        f"• С заданной группой: <b>{chats_with_group or 0}</b>\n"
        f"• Активные ответы в чате: <b>{active_chats or 0}</b>\n"
        f"• Утренние уведы в чаты: <b>{chats_with_notifs or 0}</b>\n\n"
        "🧠 <b>In-Memory Кэш (RAM O(1)):</b>\n"
        f"• Статус: {cache_ready_str}\n"
        f"• Групп в кэше: <b>{cache_info['groups_count']}</b>\n"
        f"• Учебных недель: <b>{cache_info['weeks_count']}</b>\n"
        f"• Занятий в памяти: <b>{cache_info['lessons_count']}</b>\n"
        f"• Индекс преподавателей: <b>{cache_info['teachers_count']} чел.</b>\n\n"
        "🗄 <b>База данных (PostgreSQL):</b>\n"
        f"• Групп: <b>{total_groups or 0}</b> | Недель: <b>{total_weeks or 0}</b> | Пар: <b>{total_lessons or 0}</b>\n\n"
        "🌐 <b>Синхронизация bio.bsu.by:</b>\n"
        f"• Последний запуск: <code>{sync_time}</code>\n"
        f"• Обновлено пар: <b>{sync_count}</b>"
    )

    await message.answer(text)


@router.message(Command("allstats"))
async def cmd_admin_allstats(message: Message):
    async with async_session_maker() as session:
        # Загружаем все группы
        groups_res = await session.execute(select(Group).order_by(Group.course.asc(), Group.number.asc()))
        all_groups = groups_res.scalars().all()

        # Считаем пользователей по группам
        users_count_res = await session.execute(
            select(User.group_id, func.count(User.telegram_id))
            .where(User.group_id.is_not(None))
            .group_by(User.group_id)
        )
        users_by_group = dict(users_count_res.all())

        # Считаем беседы по группам
        chats_count_res = await session.execute(
            select(Chat.group_id, func.count(Chat.chat_id)).where(Chat.group_id.is_not(None)).group_by(Chat.group_id)
        )
        chats_by_group = dict(chats_count_res.all())

        # Пользователи без группы
        unreg_users = await session.scalar(select(func.count(User.telegram_id)).where(User.group_id.is_(None)))

    text = "📈 <b>Детальная статистика по курсам и группам:</b>\n\n"

    for course in range(1, 5):
        course_groups = [g for g in all_groups if g.course == course]
        course_groups.sort(key=lambda x: int(x.number) if x.number.isdigit() else 999)

        total_course_users = sum(users_by_group.get(g.id, 0) for g in course_groups)
        total_course_chats = sum(chats_by_group.get(g.id, 0) for g in course_groups)

        text += (
            f"🎓 <b>{course} КУРС</b> (Всего: <b>{total_course_users}</b> студ. | <b>{total_course_chats}</b> бесед)\n"
        )

        if not course_groups:
            text += "<i>Группы не загружены</i>\n"
        else:
            for g in course_groups:
                u_cnt = users_by_group.get(g.id, 0)
                c_cnt = chats_by_group.get(g.id, 0)
                chat_tag = f" | 💬 {c_cnt} бесед." if c_cnt > 0 else ""
                text += f"• Гр. <b>{g.number}</b> ({g.name}): <b>{u_cnt}</b> студ.{chat_tag}\n"

        text += "\n"

    text += f"👤 <b>Студенты без группы / не завершили регистрацию:</b> <b>{unreg_users or 0}</b>"

    # Защита от лимита Telegram в 4096 символов
    if len(text) > 4000:
        for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
            await message.answer(chunk)
    else:
        await message.answer(text)


@router.message(Command("sync"))
async def cmd_force_sync(message: Message, bot: Bot):
    msg = await message.answer("⏳ Синхронизирую все 4 курса с bio.bsu.by...")

    try:
        async with async_session_maker() as session:
            res = await sync_all_courses(session, bot=bot)
            await schedule_cache.reload_from_db(session)

        saved = res.get("total_lessons_saved", 0)
        changes_count = res.get("changes_count", 0)

        if changes_count > 0:
            changes_info = (
                f"\n⚡ <b>Обнаружены изменения:</b> в <b>{changes_count}</b> группах.\n"
                f"📢 <i>Экстренные уведомления с карточками изменений автоматически отправлены студентам и в беседы!</i>"
            )
        else:
            changes_info = "\n✨ <i>Изменений в сетке расписания не обнаружено.</i>"

        await msg.edit_text(
            f"✅ <b>Синхронизация успешно завершена!</b>\n\n"
            f"📚 Всего обновлено пар в базе и кэше: <b>{saved}</b>"
            f"{changes_info}"
        )
    except Exception as e:
        logger.error(f"Ошибка команды /sync: {e}")
        await msg.edit_text(f"❌ <b>Ошибка:</b> <code>{e}</code>")


@router.message(Command("tech"))
async def cmd_tech_broadcast(message: Message, command: CommandObject, bot: Bot):
    broadcast_text = command.args
    if not broadcast_text:
        await message.reply("⚠️ Формат: <code>/tech Текст сообщения</code>")
        return

    async with async_session_maker() as session:
        users = (await session.execute(select(User))).scalars().all()
        chats = (await session.execute(select(Chat))).scalars().all()

    all_targets = [u.telegram_id for u in users] + [c.chat_id for c in chats]
    total = len(all_targets)
    sent = 0
    blocked_count = 0
    bad_request_count = 0
    other_errors = 0

    status_msg = await message.answer(f"⏳ Начинаю рассылку на {total} получателей (пользователи и беседы)...")

    for target_id in all_targets:
        try:
            await bot.send_message(chat_id=target_id, text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}")
            sent += 1
        except TelegramForbiddenError:
            blocked_count += 1
        except TelegramBadRequest:
            bad_request_count += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(chat_id=target_id, text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}")
                sent += 1
            except Exception:
                other_errors += 1
        except Exception:
            other_errors += 1

        await asyncio.sleep(0.04)

    report = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего адресатов: <b>{total}</b>\n"
        f"📬 Доставлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали/кикнули: <b>{blocked_count}</b>\n"
    )
    if bad_request_count > 0:
        report += f"⚠️ Ошибок разметки: <b>{bad_request_count}</b>\n"
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
            document=FSInputFile(log_path, filename="bot_logs.txt"), caption="📄 Логи работы бота"
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить логи: {e}")
