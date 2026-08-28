from datetime import date, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database import async_session_maker
from models import User, Group, Lesson, Week
from services.formatter import (
    build_native_rich_schedule, 
    format_full_week_rich_message, 
    TIMESLOTS, 
    DAYS_NAMES
)
from services.query_parser import parse_schedule_query
from keyboards import week_nav_kb
from config import get_minsk_now
from datetime import datetime

router = Router()


def get_active_slot_id() -> int:
    now = get_minsk_now()
    cur_minutes = now.hour * 60 + now.minute
    for slot_id, times in TIMESLOTS.items():
        h, m = map(int, times["time"].split(" - ")[1].split(":"))
        if cur_minutes <= h * 60 + m:
            return slot_id
    return 1


async def fetch_lessons_for_target(session, group_id: int, course: int, target_date: date):
    monday = target_date - timedelta(days=target_date.weekday())
    week_res = await session.execute(
        select(Week).where(Week.start_date == monday, Week.course == course)
    )
    week_obj = week_res.scalar()
    
    if not week_obj:
        fallback_res = await session.execute(
            select(Week).where(Week.course == course).order_by(Week.id.desc()).limit(1)
        )
        week_obj = fallback_res.scalar()

    if not week_obj:
        return monday, []

    lessons_res = await session.execute(
        select(Lesson).where(Lesson.group_id == group_id, Lesson.week_id == week_obj.id)
    )
    return monday, lessons_res.scalars().all()


async def send_week_schedule(user: User, group: Group, target_date: date, chat_id: int, bot: Bot):
    monday = target_date - timedelta(days=target_date.weekday())
    async with async_session_maker() as session:
        monday, lessons = await fetch_lessons_for_target(session, group.id, group.course, monday)

    rich_msg = format_full_week_rich_message(
        user_name=user.first_name,
        group_name=group.name,
        user_subgroup=user.subgroup or 0,
        start_monday=monday,
        lessons=lessons
    )
    await bot.send_rich_message(
        chat_id=chat_id, 
        rich_message=rich_msg,
        reply_markup=week_nav_kb(monday)
    )


@router.callback_query(F.data.startswith("week_date_"))
async def callback_switch_week_by_date(callback: CallbackQuery, bot: Bot):
    date_str = callback.data.replace("week_date_", "")
    target_monday = datetime.strptime(date_str, "%Y-%m-%d").date()

    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if not user or not user.group_id:
            await callback.answer("Сначала зарегистрируйтесь!")
            return
        group = await session.get(Group, user.group_id)

    await callback.message.delete()
    await send_week_schedule(user, group, target_monday, callback.message.chat.id, bot)
    await callback.answer()


@router.callback_query(F.data.in_(["week_curr", "week_next"]))
async def callback_switch_week(callback: CallbackQuery, bot: Bot):
    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if not user or not user.group_id:
            await callback.answer("Сначала зарегистрируйтесь!")
            return
        group = await session.get(Group, user.group_id)

    today = get_minsk_now().date()
    monday = today - timedelta(days=today.weekday())
    target_monday = monday if callback.data == "week_curr" else monday + timedelta(days=7)
    
    await callback.message.delete()
    await send_week_schedule(user, group, target_monday, callback.message.chat.id, bot)
    await callback.answer()


@router.message(F.text)
async def handle_schedule_queries(message: Message, state: FSMContext, bot: Bot):
    if message.text.startswith("/") or "Уведы" in message.text or "Настройки" in message.text:
        return

    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user or not user.group_id:
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        group = await session.get(Group, user.group_id)

    parsed = parse_schedule_query(message.text)

    if parsed["type"] == "week":
        await send_week_schedule(user, group, parsed["date"], message.chat.id, bot)
        return

    async with async_session_maker() as session:
        monday, lessons = await fetch_lessons_for_target(session, group.id, group.course, parsed["date"])

    day_name = DAYS_NAMES[parsed["day_index"]]
    formatted_date = parsed["date"].strftime("%d.%m")

    if parsed["type"] in ("slot", "current"):
        slot_id = get_active_slot_id() if parsed["type"] == "current" else parsed["slot_id"]
        matched = [
            l for l in lessons 
            if l.day == parsed["day_index"] and l.slot_id == slot_id and 
            (l.subgroup is None or l.subgroup == user.subgroup or user.subgroup == 0)
        ]
        
        slot_info = TIMESLOTS.get(slot_id, {"order": f"{slot_id}️⃣", "time": "--:--"})
        if not matched:
            status = "сейчас нет пар" if parsed["type"] == "current" else f"нет {slot_id}-й пары"
            await message.answer(f"🌴 <b>{day_name} ({formatted_date})</b>\nУ вас {status}!")
            return
            
        l = matched[0]
        room_str = f"🚪 <b>ауд. {l.room}</b>" if l.room else "🚪 <i>ауд. ?</i>"
        loc_str = f"{room_str} ⚠️ <b>({l.address}) — ВЫЕЗД!</b>" if l.address and "курчатова" not in l.address.lower() else room_str
        teacher_str = f"👤 <i>{l.teacher}</i>" if l.teacher else "👤 <i>Преподаватель не указан</i>"
        sub_tag = f" [Подгруппа {l.subgroup}]" if l.subgroup else ""
        prefix = "⚡ <b>Текущая пара:</b>\n" if parsed["type"] == "current" else ""

        text = (
            f"{prefix}📍 <b>{day_name} ({formatted_date})</b> | {slot_info['order']} пара\n"
            f"⏰ <b>{slot_info['time']}</b> | {loc_str}\n"
            f"📚 <b>{l.subject} ({l.lesson_type}){sub_tag}</b>\n"
            f"{teacher_str}"
        )
        await message.answer(text)
        return

    rich_msg = build_native_rich_schedule(
        user_name=user.first_name,
        group_name=group.name,
        user_subgroup=user.subgroup or 0,
        day_index=parsed["day_index"],
        target_date=parsed["date"],
        lessons=lessons
    )

    await bot.send_rich_message(
        chat_id=message.chat.id,
        rich_message=rich_msg
    )