from datetime import date, datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatType

from database import async_session_maker
from models import User, Chat
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
    return None


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
    
    text += "\n💡 <i>Чтобы посмотреть расписание преподавателя, напишите его фамилию (например: <b>Кукулянская</b> или <b>пары Гричика</b>)</i>"
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

    is_group_chat = callback.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    async with async_session_maker() as session:
        if is_group_chat:
            chat_obj = await session.get(Chat, callback.message.chat.id)
            if not chat_obj or not chat_obj.group_id:
                return
            group_id = chat_obj.group_id
            target_subgroup = 0
            user_name = callback.message.chat.title or "Группа"
        else:
            user = await session.get(User, callback.from_user.id)
            if not user or not user.group_id:
                return
            group_id = user.group_id
            target_subgroup = user.subgroup or 0
            user_name = user.first_name or "Студент"

    group = schedule_cache.get_group_by_id(group_id)
    if not group:
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    await send_week_schedule(
        user_name=user_name,
        group=group,
        target_subgroup=target_subgroup,
        target_date=target_monday,
        chat_id=callback.message.chat.id,
        bot=bot
    )


@router.message(F.text)
async def handle_schedule_queries(message: Message, state: FSMContext, bot: Bot):
    if message.text.startswith("/") or "Уведы" in message.text or "Настройки" in message.text:
        return

    is_group_chat = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    # 0. Проверка настроек беседы
    if is_group_chat:
        async with async_session_maker() as session:
            chat_obj = await session.get(Chat, message.chat.id)
            if not chat_obj:
                chat_obj = Chat(chat_id=message.chat.id, title=message.chat.title)
                session.add(chat_obj)
                await session.commit()

            if not chat_obj.is_active:
                return
            chat_group_id = chat_obj.group_id

    # 1. Поиск преподавателя (In-Memory)
    now_date = get_minsk_now().date()
    teacher_match = schedule_cache.find_teacher_schedule(message.text, now_date)
    if teacher_match:
        teacher_name, monday, lessons_data = teacher_match
        rich_msg = format_teacher_rich_schedule(
            teacher_full_name=teacher_name,
            start_monday=monday,
            lessons_data=lessons_data
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 2. Парсинг запроса на расписание
    parsed = parse_schedule_query(message.text)
    if not parsed:
        # Если это не запрос расписания (например, обычное общение в беседе) — молчим
        return

    await state.clear()

    # 3. Определение целевой группы и подгруппы
    if parsed.get("target_group"):
        t_course = parsed["target_group"]["course"]
        t_num = parsed["target_group"]["group_number"]
        group = schedule_cache.find_group_by_course_and_number(t_course, t_num)
        if not group:
            await message.answer(f"⚠️ Группа <b>{t_num}</b> ({t_course} курс) не найдена в базе!")
            return
        target_subgroup = 0
        user_name = message.chat.title if is_group_chat else "Студент"
    elif is_group_chat:
        if not chat_group_id:
            return
        group = schedule_cache.get_group_by_id(chat_group_id)
        target_subgroup = 0
        user_name = message.chat.title or "Группа"
    else:
        async with async_session_maker() as session:
            user = await session.get(User, message.from_user.id)

        if not user or not user.group_id:
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        group = schedule_cache.get_group_by_id(user.group_id)
        target_subgroup = user.subgroup or 0
        user_name = user.first_name or "Студент"

    if not group:
        if not is_group_chat:
            await message.answer("⚠️ Группа не найдена. Пройдите регистрацию заново: /start")
        return

    # 4. Расписание на неделю
    if parsed["type"] == "week":
        await send_week_schedule(
            user_name=user_name,
            group=group,
            target_subgroup=target_subgroup,
            target_date=parsed["date"],
            chat_id=message.chat.id,
            bot=bot
        )
        return

    # 5. Конкретный слот или текущая пара
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

    # 6. Дневная карточка расписания
    rich_msg = build_native_rich_schedule(
        user_name=user_name,
        group_name=group.name,
        user_subgroup=target_subgroup,
        day_index=parsed["day_index"],
        target_date=parsed["date"],
        lessons=lessons
    )

    await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)