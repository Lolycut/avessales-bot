import asyncio
from datetime import date, timedelta
from sqlalchemy import select
from aiogram import Bot

from config import logger, get_minsk_now
from database import async_session_maker
from models import User, Group, Week, Lesson
from services.formatter import build_native_rich_schedule

NOTIFY_HOUR = 7
NOTIFY_MINUTE = 45


async def get_today_lessons_from_db(session, group_id: int, course: int, today: date):
    monday = today - timedelta(days=today.weekday())

    # Ищем точную неделю, либо последнюю актуальную
    week_res = await session.execute(
        select(Week).where(Week.course == course, Week.start_date == monday)
    )
    week = week_res.scalar_one_or_none()

    if not week:
        week_res = await session.execute(
            select(Week)
            .join(Lesson, Lesson.week_id == Week.id)
            .where(Week.course == course, Lesson.group_id == group_id)
            .order_by(Week.start_date.desc())
            .limit(1)
        )
        week = week_res.scalar_one_or_none()

    if not week:
        return []

    lessons_res = await session.execute(
        select(Lesson).where(Lesson.group_id == group_id, Lesson.week_id == week.id)
    )
    return lessons_res.scalars().all()


async def send_to_user(bot: Bot, user: User, today: date, day_index: int, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        if not user.group_id:
            return False

        async with async_session_maker() as session:
            group = await session.get(Group, user.group_id)
            if not group:
                return False

            lessons = await get_today_lessons_from_db(session, group.id, group.course, today)

        # Фильтруем пары на сегодня с учетом подгруппы
        today_lessons = [
            l for l in lessons 
            if l.day == day_index and (l.subgroup is None or l.subgroup == user.subgroup or user.subgroup == 0 or user.subgroup is None)
        ]

        if not today_lessons:
            return False

        rich_card = build_native_rich_schedule(
            user_name=user.first_name or "Студент",
            group_name=group.name,
            user_subgroup=user.subgroup or 0,
            day_index=day_index,
            target_date=today,
            lessons=lessons
        )

        try:
            await bot.send_rich_message(chat_id=user.telegram_id, rich_message=rich_card)
            await asyncio.sleep(0.04)  # Равномерный RPS (до 25 сообщений/сек)
            return True
        except Exception as e:
            logger.warning(f"Ошибка отправки уведомления {user.telegram_id}: {e}")
            return False


async def send_morning_schedule(bot: Bot):
    today = get_minsk_now().date()
    day_index = today.weekday()
    if day_index > 5:  # В воскресенье не рассылаем
        return

    logger.info("🌅 Запуск утренней рассылки расписания (07:45 Минск)...")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.notifications_enabled == True, User.group_id.is_not(None))
        )
        users = result.scalars().all()

    if not users:
        return

    semaphore = asyncio.Semaphore(25)
    tasks = [send_to_user(bot, user, today, day_index, semaphore) for user in users]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sent_count = sum(1 for r in results if r is True)
    logger.info(f"✅ Утренняя рассылка завершена. Доставлено: {sent_count}/{len(users)}")


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