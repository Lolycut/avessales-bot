from datetime import date, timedelta, datetime
from typing import Optional, List, Dict, Any
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from database import async_session_maker
from services.formatter import (
    build_native_rich_schedule, 
    format_full_week_rich_message, 
    format_teacher_rich_schedule,
    TIMESLOTS, 
    DAYS_NAMES
)
from services.query_parser import parse_schedule_query
from services.cache import (
    get_cached_user, 
    get_cached_group, 
    GroupDTO,
    LessonDTO,
    LESSONS_CACHE, 
    GROUPS_CACHE,
    TEACHERS_CACHE
)
from keyboards import week_nav_kb
from config import get_minsk_now, logger

router = Router()


def get_active_slot_id() -> int:
    now = get_minsk_now()
    cur_minutes = now.hour * 60 + now.minute
    for slot_id, times in TIMESLOTS.items():
        h, m = map(int, times["time"].split(" - ")[1].split(":"))
        if cur_minutes <= h * 60 + m:
            return slot_id
    return 1


def fetch_lessons_from_cache(group_id: int, target_date: date) -> tuple[date, List[LessonDTO]]:
    monday = target_date - timedelta(days=target_date.weekday())
    lessons = LESSONS_CACHE.get((group_id, monday))
    if lessons is not None:
        return monday, lessons

    available_mondays = [m for (g_id, m) in LESSONS_CACHE.keys() if g_id == group_id]
    if available_mondays:
        latest_monday = max(available_mondays)
        return latest_monday, LESSONS_CACHE.get((group_id, latest_monday), [])

    return monday, []


async def send_week_schedule(user_name: str, group: GroupDTO, target_subgroup: int, target_date: date, chat_id: int, bot: Bot):
    monday, lessons = fetch_lessons_from_cache(group.id, target_date)
    rich_msg = format_full_week_rich_message(
        user_name=user_name,
        group_name=group.name,
        user_subgroup=target_subgroup,
        start_monday=monday,
        lessons=lessons
    )
    await bot.send_rich_message(
        chat_id=chat_id, 
        rich_message=rich_msg,
        reply_markup=week_nav_kb(monday)
    )


async def try_find_teacher_schedule(query_text: str, target_date: date) -> Optional[tuple[str, date, List[Dict[str, Any]]]]:
    clean = query_text.replace("где", "").replace("препод", "").replace("преподаватель", "").replace("пары", "").replace("расписание", "").strip().lower()
    words = clean.split()
    if not words:
        return None

    matched_teacher = None
    for word in words:
        if len(word) < 3:
            continue
        for t in TEACHERS_CACHE:
            if word in t.lower():
                matched_teacher = t
                break
        if matched_teacher:
            break

    if not matched_teacher:
        return None

    monday = target_date - timedelta(days=target_date.weekday())

    matched_lessons = []
    for (g_id, m_date), l_list in LESSONS_CACHE.items():
        if m_date == monday:
            group = GROUPS_CACHE.get(g_id)
            for l in l_list:
                if l.teacher == matched_teacher:
                    matched_lessons.append((l, group))

    grouped_slots: Dict[tuple, Dict[str, Any]] = {}
    for lesson, group in matched_lessons:
        g_tag = f"{group.course}-{group.number}" if group else "?"
        key = (lesson.day, lesson.slot_id, lesson.subject, lesson.lesson_type, lesson.room)
        if key not in grouped_slots:
            grouped_slots[key] = {
                "day": lesson.day,
                "slot_id": lesson.slot_id,
                "subject": lesson.subject,
                "lesson_type": lesson.lesson_type,
                "room": lesson.room,
                "address": lesson.address,
                "subgroup": lesson.subgroup,
                "groups": [g_tag]
            }
        else:
            if g_tag not in grouped_slots[key]["groups"]:
                grouped_slots[key]["groups"].append(g_tag)

    lessons_list = []
    for item in grouped_slots.values():
        item["groups_display"] = ", ".join(item["groups"])
        lessons_list.append(item)

    return matched_teacher, monday, lessons_list


@router.message(Command("teachers"))
@router.message(Command("prep"))
async def cmd_list_teachers(message: Message):
    if not TEACHERS_CACHE:
        await message.answer("Преподаватели пока не синхронизированы в базе")
        return

    text = "👨‍🏫 <b>Преподаватели факультета в базе:</b>\n\n"
    for t in TEACHERS_CACHE[:40]:
        text += f"• <code>{t}</code>\n"
    
    text += "\n💡 <i>Чтобы посмотреть расписание преподавателя, напишите его фамилию (например: <b>Кукулянская</b>)</i>"
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
        user = await get_cached_user(session, callback.from_user.id)
        if not user or not user.group_id:
            try:
                await callback.answer("Сначала зарегистрируйтесь!", show_alert=True)
            except TelegramBadRequest:
                pass
            return
        group = await get_cached_group(session, user.group_id)

    if not group:
        return

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        return
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение при смене недели: {e}")

    try:
        await send_week_schedule(
            user_name=user.first_name,
            group=group,
            target_subgroup=user.subgroup or 0,
            target_date=target_monday,
            chat_id=callback.message.chat.id,
            bot=bot
        )
    except Exception as e:
        logger.error(f"Ошибка отправки недельного расписания: {e}")


@router.message(F.text)
async def handle_schedule_queries(message: Message, state: FSMContext, bot: Bot):
    if message.text.startswith("/") or "Уведы" in message.text or "Настройки" in message.text:
        return

    await state.clear()
    parsed = parse_schedule_query(message.text)

    teacher_match = await try_find_teacher_schedule(message.text, parsed["date"])
    if teacher_match:
        teacher_name, monday, lessons_data = teacher_match
        rich_msg = format_teacher_rich_schedule(
            teacher_full_name=teacher_name,
            start_monday=monday,
            lessons_data=lessons_data
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    async with async_session_maker() as session:
        user = await get_cached_user(session, message.from_user.id)
        if not user or not user.group_id:
            await message.answer("Сначала пройдите регистрацию: /start")
            return

        if parsed.get("target_group"):
            t_course = parsed["target_group"]["course"]
            t_num = parsed["target_group"]["group_number"]
            target_group = next(
                (g for g in GROUPS_CACHE.values() if g.course == t_course and (g.number == t_num or t_num in g.number)),
                None
            )
            if not target_group:
                await message.answer(f"⚠️ Группа <b>{t_num}</b> ({t_course} курс) не найдена в базе!")
                return
            group = target_group
            target_subgroup = 0
        else:
            group = await get_cached_group(session, user.group_id)
            target_subgroup = user.subgroup or 0

    if not group:
        await message.answer("⚠️ Ваша группа не найдена. Попробуйте перерегистрироваться через /start")
        return

    # 3. Расписание на неделю
    if parsed["type"] == "week":
        await send_week_schedule(
            user_name=user.first_name,
            group=group,
            target_subgroup=target_subgroup,
            target_date=parsed["date"],
            chat_id=message.chat.id,
            bot=bot
        )
        return

    monday, lessons = fetch_lessons_from_cache(group.id, parsed["date"])
    day_name = DAYS_NAMES[parsed["day_index"]]
    formatted_date = parsed["date"].strftime("%d.%m")

    if parsed["type"] in ("slot", "current"):
        slot_id = get_active_slot_id() if parsed["type"] == "current" else parsed["slot_id"]
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

    rich_msg = build_native_rich_schedule(
        user_name=user.first_name,
        group_name=group.name,
        user_subgroup=target_subgroup,
        day_index=parsed["day_index"],
        target_date=parsed["date"],
        lessons=lessons
    )

    await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)