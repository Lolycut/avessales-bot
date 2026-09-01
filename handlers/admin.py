import asyncio
import os
import html
from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select, func

from database import async_session_maker
from models import User, Group, Lesson, Week, Chat
from services.schedule_cache import schedule_cache
from services.metrics import metrics_service
from services.api_client import sync_all_courses, LAST_SYNC_INFO
from config import ADMIN_IDS, logger

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
        "• <code>/stats</code> (или <code>/metrics</code>) — живые метрики активности, БД и кэш\n"
        "• <code>/allstats</code> — срез студентов и бесед по каждому курсу и группе\n"
        "• <code>/sync</code> — принудительная синхронизация с bio.bsu.by\n"
        "• <code>/tech Текст</code> — рассылка оповещения студентам и в беседы\n"
        "• <code>/logs</code> — скачать файл логов (bot.log)"
    )
    await message.answer(text)


@router.message(Command("stats"))
@router.message(Command("metrics"))
async def cmd_admin_stats(message: Message):
    # 1. Живые метрики активности
    m = metrics_service.get_stats()

    # 2. Данные из базы данных (PostgreSQL)
    async with async_session_maker() as session:
        # Пользователи
        total_users = await session.scalar(select(func.count(User.telegram_id)))
        users_with_group = await session.scalar(
            select(func.count(User.telegram_id)).where(User.group_id.is_not(None))
        )
        morning_users = await session.scalar(
            select(func.count(User.telegram_id)).where(User.notifications_enabled == True)
        )
        change_users = await session.scalar(
            select(func.count(User.telegram_id)).where(User.change_notifications_enabled == True)
        )

        # Беседы
        total_chats = await session.scalar(select(func.count(Chat.chat_id)))
        chats_with_group = await session.scalar(
            select(func.count(Chat.chat_id)).where(Chat.group_id.is_not(None))
        )
        active_chats = await session.scalar(
            select(func.count(Chat.chat_id)).where(Chat.is_active == True)
        )
        morning_chats = await session.scalar(
            select(func.count(Chat.chat_id)).where(Chat.notifications_enabled == True)
        )
        change_chats = await session.scalar(
            select(func.count(Chat.chat_id)).where(Chat.change_notifications_enabled == True)
        )

        # БД сущности
        total_groups = await session.scalar(select(func.count(Group.id)))
        total_lessons = await session.scalar(select(func.count(Lesson.id)))
        total_weeks = await session.scalar(select(func.count(Week.id)))

    # 3. Состояние In-Memory кэша
    cache_info = schedule_cache.get_cache_stats()
    cache_ready_str = "🟢 Готов к работе" if cache_info["is_ready"] else "🔴 Не инициализирован"

    sync_time = LAST_SYNC_INFO.get("timestamp") or "Еще не запускалась"
    sync_count = LAST_SYNC_INFO.get("total_lessons_saved", 0)

    text = (
        f"📊 <b>Живые метрики и системное состояние</b>\n"
        f"<i>Сервер запущен: {m['boot_time']}</i>\n\n"
        f"📈 <b>Активность за сегодня ({m['today_date']}):</b>\n"
        f"• 👥 Уникальных пользователей (DAU): <b>{m['dau']}</b>\n"
        f"• 💬 Активных бесед (DAC): <b>{m['dac']}</b>\n"
        f"• ⚡ Запросов за сутки: <b>{m['daily_requests']}</b>\n"
        f"• 🕒 Пиковый час нагрузки: <b>{m['peak_hour']}</b>\n\n"
        f"🌐 <b>Всего с момента запуска:</b>\n"
        f"• 🚀 Всего взаимодействий: <b>{m['total_requests']}</b>\n"
        f"• 👤 В личке: <b>{m['total_private']}</b> | 👥 В беседах: <b>{m['total_group']}</b>\n"
        f"• 💬 Текстовых сообщений: <b>{m['total_messages']}</b> | 🔘 Нажатий кнопок: <b>{m['total_callbacks']}</b>\n\n"
        f"👤 <b>Пользователи в БД:</b>\n"
        f"• Всего в базе: <b>{total_users or 0}</b> (с группой: <b>{users_with_group or 0}</b>)\n"
        f"• Подписки: 🌅 Утро (07:45): <b>{morning_users or 0}</b> | ⚡ Изменения: <b>{change_users or 0}</b>\n\n"
        f"👥 <b>Беседы в БД:</b>\n"
        f"• Всего подключено: <b>{total_chats or 0}</b> (с группой: <b>{chats_with_group or 0}</b>)\n"
        f"• Активные ответы «Бот»: <b>{active_chats or 0}</b>\n"
        f"• Подписки: 🌅 Утро: <b>{morning_chats or 0}</b> | ⚡ Изменения: <b>{change_chats or 0}</b>\n\n"
        f"🧠 <b>In-Memory Кэш (RAM O(1)):</b>\n"
        f"• Статус: {cache_ready_str}\n"
        f"• Групп: <b>{cache_info['groups_count']}</b> | Недель: <b>{cache_info['weeks_count']}</b> | Пар: <b>{cache_info['lessons_count']}</b>\n"
        f"• Индекс преподавателей: <b>{cache_info['teachers_count']} чел.</b>\n\n"
        f"🗄 <b>PostgreSQL:</b> {total_groups or 0} групп | {total_weeks or 0} недель | {total_lessons or 0} пар\n"
        f"🌐 <b>Синхронизация bio.bsu.by:</b> <code>{sync_time}</code> (пар: {sync_count})"
    )

    await message.answer(text)


@router.message(Command("allstats"))
async def cmd_admin_allstats(message: Message):
    async with async_session_maker() as session:
        groups_res = await session.execute(
            select(Group).order_by(Group.course.asc(), Group.number.asc())
        )
        all_groups = groups_res.scalars().all()

        users_count_res = await session.execute(
            select(User.group_id, func.count(User.telegram_id))
            .where(User.group_id.is_not(None))
            .group_by(User.group_id)
        )
        users_by_group = dict(users_count_res.all())

        chats_count_res = await session.execute(
            select(Chat.group_id, func.count(Chat.chat_id))
            .where(Chat.group_id.is_not(None))
            .group_by(Chat.group_id)
        )
        chats_by_group = dict(chats_count_res.all())

        unreg_users = await session.scalar(
            select(func.count(User.telegram_id)).where(User.group_id.is_(None))
        )

    total_students = sum(users_by_group.values())
    total_chats = sum(chats_by_group.values())

    header_text = (
        f"📊 <b>Детальная статистика по факультету</b>\n\n"
        f"👥 Всего студентов в группах: <b>{total_students}</b>\n"
        f"💬 Всего бесед подключено: <b>{total_chats}</b>\n"
        f"👤 Студентов без группы: <b>{unreg_users or 0}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(header_text)

    for course in range(1, 6):
        course_groups = [g for g in all_groups if g.course == course]
        course_groups.sort(
            key=lambda x: int(str(x.number)) if x.number and str(x.number).isdigit() else 999
        )

        if not course_groups:
            continue

        total_course_users = sum(users_by_group.get(g.id, 0) for g in course_groups)
        total_course_chats = sum(chats_by_group.get(g.id, 0) for g in course_groups)

        course_text = (
            f"🎓 <b>{course} КУРС</b> (Студентов: <b>{total_course_users}</b> | Бесед: <b>{total_course_chats}</b>):\n\n"
        )

        for g in course_groups:
            u_cnt = users_by_group.get(g.id, 0)
            c_cnt = chats_by_group.get(g.id, 0)
            chat_tag = f" | 💬 {c_cnt} бесед." if c_cnt > 0 else ""
            
            safe_num = html.escape(str(g.number))
            safe_name = html.escape(g.name or "Без названия")
            
            course_text += f"• Гр. <b>{safe_num}</b> ({safe_name}): <b>{u_cnt}</b> студ.{chat_tag}\n"

        await message.answer(course_text)


@router.message(Command("sync"))
async def cmd_force_sync(message: Message, bot: Bot):
    msg = await message.answer("⏳ Синхронизирую все 5 курсов с bio.bsu.by...")
    
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
            await bot.send_message(
                chat_id=target_id, 
                text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}"
            )
            sent += 1
        except TelegramForbiddenError:
            blocked_count += 1
        except TelegramBadRequest:
            bad_request_count += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(
                    chat_id=target_id, 
                    text=f"🛠 <b>ТЕХНИЧЕСКОЕ ОПОВЕЩЕНИЕ</b>\n\n{broadcast_text}"
                )
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
            document=FSInputFile(log_path, filename="bot_logs.txt"), 
            caption="📄 Логи работы бота"
        )
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить логи: {e}")