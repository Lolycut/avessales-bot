from datetime import date, datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from database import async_session_maker
from models import User
from services.dto import GroupDTO
from services.schedule_cache import schedule_cache
from services.formatter import (
    build_native_rich_schedule, 
    format_full_week_rich_message, 
    format_teacher_rich_schedule,
    TIMESLOTS, 
    DAYS_NAMES
)
from services.query_parser import parse_schedule_query
from keyboards import week_nav_kb
from config import get_minsk_now

router = Router()


def get_active_slot_id() -> int | None:
    now = get_minsk_now()
    cur_minutes = now.hour * 60 + now.minute
    for slot_id, times in TIMESLOTS.items():
        h, m = map(int, times["time"].split(" - ")[1].split(":"))
        if cur_minutes <= h * 60 + m:
            return slot_id
    return None  # Все пары на сегодня закончились


async def send_week_schedule(
    user_name: str, 
    group: GroupDTO, 
    target_subgroup: int, 
    target_date: date, 
    chat_id: int, 
    bot: Bot
):
    actual_monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, target_date)
    rich_msg = format_full_week_rich_message(
        user_name=user_name,
        group_name=group.name,
        user_subgroup=target_subgroup,
        start_monday=actual_monday,
        lessons=lessons
    )
    await bot.send_rich_message(
        chat_id=chat_id, 
        rich_message=rich_msg,
        reply_markup=week_nav_kb(actual_monday)
    )


@router.message(Command("teachers"))
@router.message(Command("prep"))
async def cmd_list_teachers(message: Message):
    teachers = schedule_cache.get_all_teachers()[:40]

    if not teachers:
        await message.answer("Преподаватели пока не найдены в базе данных")
        return

    text = "👨‍🏫 <b>Преподаватели факультета в базе:</b>\n\n"
    for t in teachers:
        text += f"• <code>{t}</code>\n"
    
    text += "\n💡 <i>Чтобы посмотреть расписание преподавателя, напишите его фамилию (например: <b>Кукулянская</b> или <b>пары Сысова</b>)</i>"
    await message.answer(text)


@router.callback_query(F.data.startswith("week_date_"))
async def callback_switch_week_by_date(callback: CallbackQuery, bot: Bot):
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

    date_str = callback.data.replace("week_date_", "")
    try:
        target_monday = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return

    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if not user or not user.group_id:
            return

    group = schedule_cache.get_group_by_id(user.group_id)
    if not group:
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    await send_week_schedule(
        user_name=user.first_name or "Студент",
        group=group,
        target_subgroup=user.subgroup or 0,
        target_date=target_monday,
        chat_id=callback.message.chat.id,
        bot=bot
    )


@router.message(F.text)
async def handle_schedule_queries(message: Message, state: FSMContext, bot: Bot):
    if message.text.startswith("/") or "Уведы" in message.text or "Настройки" in message.text:
        return

    await state.clear()
    parsed = parse_schedule_query(message.text)

    # 1. Преподаватель (In-Memory)
    teacher_match = schedule_cache.find_teacher_schedule(message.text, parsed["date"])
    if teacher_match:
        teacher_name, monday, lessons_data = teacher_match
        rich_msg = format_teacher_rich_schedule(
            teacher_full_name=teacher_name,
            start_monday=monday,
            lessons_data=lessons_data
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 2. Пользователь (БД)
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)

    if not user or not user.group_id:
        await message.answer("Сначала пройдите регистрацию: /start")
        return

    # 3. Группа (In-Memory)
    if parsed.get("target_group"):
        t_course = parsed["target_group"]["course"]
        t_num = parsed["target_group"]["group_number"]
        group = schedule_cache.find_group_by_course_and_number(t_course, t_num)
        if not group:
            await message.answer(f"⚠️ Группа <b>{t_num}</b> ({t_course} курс) не найдена в базе!")
            return
        target_subgroup = 0
    else:
        group = schedule_cache.get_group_by_id(user.group_id)
        target_subgroup = user.subgroup or 0

    if not group:
        await message.answer("⚠️ Группа не найдена. Пройдите регистрацию заново: /start")
        return

    # 4. Неделя
    if parsed["type"] == "week":
        await send_week_schedule(
            user_name=user.first_name or "Студент",
            group=group,
            target_subgroup=target_subgroup,
            target_date=parsed["date"],
            chat_id=message.chat.id,
            bot=bot
        )
        return

    # 5. День / Слот
    monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, parsed["date"])
    day_name = DAYS_NAMES[parsed["day_index"]]
    formatted_date = parsed["date"].strftime("%d.%m")

    if parsed["type"] in ("slot", "current"):
        if parsed["type"] == "current":
            slot_id = get_active_slot_id()
            if slot_id is None:
                await message.answer(f"🌴 <b>{day_name} ({formatted_date})</b> | {group.name}\nВсе пары на сегодня уже закончились! Отдыхайте ✨")
                return
        else:
            slot_id = parsed["slot_id"]

        matched = [
            l for l in lessons 
            if l.day == parsed["day_index"] and l.slot_id == slot_id and 
            (l.subgroup is None or l.subgroup == target_subgroup or target_subgroup == 0)
        ]
        
        slot_info = TIMESLOTS.get(slot_id, {"order": f"{slot_id}️⃣", "time": "--:--"})
        if not matched:
            status = "сейчас нет пар" if parsed["type"] == "current" else f"нет {slot_id}-й пары"
            await message.answer(f"🌴 <b>{day_name} ({formatted_date})</b> | {group.name}\nУ вас {status}!")
            return
            
        l = matched[0]
        room_str = f"🚪 <b>ауд. {l.room}</b>" if l.room else "🚪 <i>ауд. ?</i>"
        loc_str = f"{room_str} ⚠️ <b>({l.address}) — ВЫЕЗД!</b>" if l.address and "курчатова" not in l.address.lower() else room_str
        teacher_str = f"👤 <i>{l.teacher}</i>" if l.teacher else "👤 <i>Преподаватель не указан</i>"
        sub_tag = f" [Подгруппа {l.subgroup}]" if l.subgroup else ""
        prefix = f"⚡ <b>Пара ({group.number} группа):</b>\n" if parsed["type"] == "current" else ""

        text = (
            f"{prefix}📍 <b>{day_name} ({formatted_date})</b> | {slot_info['order']} пара ({group.number} гр.)\n"
            f"⏰ <b>{slot_info['time']}</b> | {loc_str}\n"
            f"📚 <b>{l.subject} ({l.lesson_type}){sub_tag}</b>\n"
            f"{teacher_str}"
        )
        await message.answer(text)
        return

    # 6. Дневная карточка
    rich_msg = build_native_rich_schedule(
        user_name=user.first_name or "Студент",
        group_name=group.name,
        user_subgroup=target_subgroup,
        day_index=parsed["day_index"],
        target_date=parsed["date"],
        lessons=lessons
    )

    await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)