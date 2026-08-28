import asyncio
from datetime import date, timedelta
from sqlalchemy import select
from aiogram import Bot

from config import logger, get_minsk_now
from database import async_session_maker
from models import User, Group, Lesson, Week
from services.formatter import build_native_rich_schedule

NOTIFY_HOUR = 7
NOTIFY_MINUTE = 45

async def send_morning_schedule(bot: Bot):
    today = get_minsk_now().date()
    day_index = today.weekday()
    if day_index > 5:
        return

    logger.info("🌅 Запуск утренней рассылки расписания...")
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.notifications_enabled == True, User.group_id.is_not(None))
        )
        users = result.scalars().all()
        if not users:
            return

        sent_count = 0
        for user in users:
            group = await session.get(Group, user.group_id)
            if not group:
                continue

            monday = today - timedelta(days=today.weekday())
            week_res = await session.execute(
                select(Week).where(Week.start_date == monday, Week.course == group.course)
            )
            week_obj = week_res.scalar()
            if not week_obj:
                continue

            res_lessons = await session.execute(
                select(Lesson).where(Lesson.group_id == user.group_id, Lesson.week_id == week_obj.id)
            )
            lessons = res_lessons.scalars().all()

            today_lessons = [
                l for l in lessons 
                if l.day == day_index and (l.subgroup is None or l.subgroup == user.subgroup or user.subgroup == 0)
            ]

            if not today_lessons:
                continue

            rich_card = build_native_rich_schedule(
                user_name=user.first_name,
                group_name=group.name,
                user_subgroup=user.subgroup or 0,
                day_index=day_index,
                target_date=today,
                lessons=lessons
            )

            try:
                await bot.send_rich_message(chat_id=user.telegram_id, rich_message=rich_card)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Ошибка отправки уведомления {user.telegram_id}: {e}")

            await asyncio.sleep(0.05)

    logger.info(f"✅ Утренняя рассылка завершена. Доставлено: {sent_count}")

async def morning_notifications_loop(bot: Bot):
    last_sent_date = None
    while True:
        try:
            now = get_minsk_now()
            today = now.date()
            if now.hour == NOTIFY_HOUR and now.minute == NOTIFY_MINUTE and last_sent_date != today:
                last_sent_date = today
                await send_morning_schedule(bot)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле уведомлений: {e}")
            await asyncio.sleep(60)