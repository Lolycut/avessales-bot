import asyncio
from datetime import date
from sqlalchemy import select
from aiogram import Bot

from config import logger, get_minsk_now
from database import async_session_maker
from models import User, Chat
from services.schedule_cache import schedule_cache
from services.formatter import build_native_rich_schedule

NOTIFY_HOUR = 7
NOTIFY_MINUTE = 45


async def send_to_recipient(
    bot: Bot, 
    target_id: int, 
    group_id: int, 
    subgroup: int, 
    name: str, 
    today: date, 
    day_index: int, 
    semaphore: asyncio.Semaphore
) -> bool:
    async with semaphore:
        group = schedule_cache.get_group_by_id(group_id)
        if not group:
            return False

        actual_monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, today)

        # Фильтруем пары на сегодня с учетом подгруппы
        today_lessons = [
            l for l in lessons 
            if l.day == day_index and (l.subgroup is None or l.subgroup == subgroup or subgroup == 0)
        ]

        if not today_lessons:
            return False

        rich_card = build_native_rich_schedule(
            user_name=name,
            group_name=group.name,
            user_subgroup=subgroup,
            day_index=day_index,
            target_date=today,
            lessons=lessons
        )

        try:
            await bot.send_rich_message(chat_id=target_id, rich_message=rich_card)
            await asyncio.sleep(0.04)  # Равномерный RPS (до 25 сообщений/сек)
            return True
        except Exception as e:
            logger.warning(f"Ошибка отправки уведомления получателю {target_id}: {e}")
            return False


async def send_morning_schedule(bot: Bot):
    today = get_minsk_now().date()
    day_index = today.weekday()
    if day_index > 5:  # В воскресенье не рассылаем
        return

    logger.info("🌅 Запуск утренней рассылки расписания (07:45 Минск)...")
    
    async with async_session_maker() as session:
        # Студенты в ЛС
        users_res = await session.execute(
            select(User).where(User.notifications_enabled == True, User.group_id.is_not(None))
        )
        users = users_res.scalars().all()

        # Беседы групп
        chats_res = await session.execute(
            select(Chat).where(Chat.notifications_enabled == True, Chat.group_id.is_not(None))
        )
        chats = chats_res.scalars().all()

    if not users and not chats:
        return

    semaphore = asyncio.Semaphore(25)
    tasks = []

    for u in users:
        tasks.append(
            send_to_recipient(
                bot=bot,
                target_id=u.telegram_id,
                group_id=u.group_id,
                subgroup=u.subgroup or 0,
                name=u.first_name or "Студент",
                today=today,
                day_index=day_index,
                semaphore=semaphore
            )
        )

    for c in chats:
        tasks.append(
            send_to_recipient(
                bot=bot,
                target_id=c.chat_id,
                group_id=c.group_id,
                subgroup=0,  # Для беседы отправляем полную группу
                name=c.title or "Группа",
                today=today,
                day_index=day_index,
                semaphore=semaphore
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    sent_count = sum(1 for r in results if r is True)
    logger.info(f"✅ Утренняя рассылка завершена. Доставлено: {sent_count}/{len(tasks)}")


async def morning_notifications_loop(bot: Bot):
    last_sent_date = None
    while True:
        try:
            now = get_minsk_now()
            today = now.date()
            if now.hour == NOTIFY_HOUR and now.minute == NOTIFY_MINUTE and last_sent_date != today:
                last_sent_date = today
                await send_morning_schedule(bot)
            await asyncio.sleep(20)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле уведомлений: {e}")
            await asyncio.sleep(60)