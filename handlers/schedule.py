import re
from datetime import date, datetime, timedelta
from collections import defaultdict
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
    format_subject_rich_schedule,
    format_room_rich_schedule,
    format_free_rooms_day_summary_rich,
    format_free_rooms_rich_message,
    build_specializations_rich_message,
    short_name,
    TIMESLOTS, 
    DAYS_NAMES
)
from services.query_parser import parse_schedule_query
from keyboards import week_nav_kb, spec_view_toggle_kb
from config import get_minsk_now

router = Router()


def get_group_display_title(group: GroupDTO) -> str:
    clean_num = str(group.number).strip()
    if clean_num.startswith(f"{group.course}-"):
        tag = f"Гр. {clean_num}"
    else:
        tag = f"Гр. {group.course}-{clean_num}"
    return f"{tag} • {group.name}"


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
    group_title = get_group_display_title(group)

    has_offcampus = any(
        l.address and "курчатова" not in l.address.lower()
        and (l.subgroup is None or l.subgroup == target_subgroup or target_subgroup == 0)
        for l in lessons
    )

    has_specializations = any(
        l.specialization_order is not None or (l.common_discipline and not l.subgroup)
        for l in lessons
    )

    rich_msg = format_full_week_rich_message(
        user_name=user_name,
        group_name=group_title,
        user_subgroup=target_subgroup,
        start_monday=actual_monday,
        lessons=lessons
    )
    await bot.send_rich_message(
        chat_id=chat_id, 
        rich_message=rich_msg,
        reply_markup=week_nav_kb(
            actual_monday, 
            group_id=group.id, 
            subgroup=target_subgroup,
            has_offcampus=has_offcampus,
            has_specializations=has_specializations
        )
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

    raw_payload = callback.data.replace("week_date_", "")
    parts = raw_payload.split("_")
    date_str = parts[0]
    try:
        target_monday = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return

    is_group_chat = callback.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    if len(parts) >= 3 and parts[1].isdigit():
        group_id = int(parts[1])
        target_subgroup = int(parts[2]) if parts[2].isdigit() else 0
        user_name = callback.message.chat.title if is_group_chat else (callback.from_user.first_name or "Студент")
    else:
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


@router.callback_query(F.data.startswith("week_loc_"))
async def callback_show_offcampus_locations(callback: CallbackQuery):
    raw_payload = callback.data.replace("week_loc_", "")
    parts = raw_payload.split("_")
    date_str = parts[0]

    try:
        target_monday = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await callback.answer()
        return

    is_group_chat = callback.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    if len(parts) >= 3 and parts[1].isdigit():
        group_id = int(parts[1])
        target_subgroup = int(parts[2]) if parts[2].isdigit() else 0
    else:
        async with async_session_maker() as session:
            if is_group_chat:
                chat_obj = await session.get(Chat, callback.message.chat.id)
                if not chat_obj or not chat_obj.group_id:
                    await callback.answer("Группа не выбрана", show_alert=True)
                    return
                group_id = chat_obj.group_id
                target_subgroup = 0
            else:
                user = await session.get(User, callback.from_user.id)
                if not user or not user.group_id:
                    await callback.answer("Сначала выберите группу: /start", show_alert=True)
                    return
                group_id = user.group_id
                target_subgroup = user.subgroup or 0

    group = schedule_cache.get_group_by_id(group_id)
    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    actual_monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, target_monday)

    offcampus_lessons = [
        l for l in lessons
        if l.address and "курчатова" not in l.address.lower()
        and (l.subgroup is None or l.subgroup == target_subgroup or target_subgroup == 0)
    ]

    if not offcampus_lessons:
        await callback.answer("🎉 На этой неделе все пары проходят на родине (Курчатова 10)!", show_alert=True)
        return

    await callback.answer()

    by_days = defaultdict(list)
    for l in offcampus_lessons:
        by_days[l.day].append(l)

    group_title = get_group_display_title(group)
    end_saturday = actual_monday + timedelta(days=5)

    text_blocks = [
        f"🚗 <b>Выездные пары (не на Курчатова 10):</b>\n"
        f"👥 <b>{group_title}</b>\n"
        f"🗓 <b>{actual_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    ]

    for day_i in sorted(by_days.keys()):
        day_date = actual_monday + timedelta(days=day_i)
        day_name = DAYS_NAMES[day_i]
        day_lessons = by_days[day_i]
        day_lessons.sort(key=lambda x: (x.slot_id, x.subgroup or 0))

        text_blocks.append(f"\n📍 <b>{day_name} ({day_date.strftime('%d.%m')}):</b>")

        for l in day_lessons:
            slot_info = TIMESLOTS.get(l.slot_id, {"order": str(l.slot_id), "time": "--:--"})
            start_time = slot_info["time"].split(" - ")[0]
            sub_tag = f" [п/г {l.subgroup}]" if l.subgroup else ""
            type_tag = f" [{l.lesson_type}]" if l.lesson_type else ""
            room_tag = f"ауд. {l.room}" if l.room else "ауд. —"
            teacher_tag = f"\n   👤 <i>{short_name(l.teacher)}</i>" if l.teacher else ""

            card = (
                f"• <b>{slot_info['order']} пара ({start_time})</b> | {room_tag}\n"
                f"   📚 <b>{l.subject}{type_tag}{sub_tag}</b>{teacher_tag}\n"
                f"   🏢 <b>Адрес:</b> <code>{l.address}</code>"
            )
            text_blocks.append(card)

    await callback.message.reply("\n".join(text_blocks))


@router.callback_query(F.data.startswith("week_spec_"))
async def callback_show_week_specializations(callback: CallbackQuery, bot: Bot):
    raw_payload = callback.data.replace("week_spec_", "")
    parts = raw_payload.split("_")
    date_str = parts[0]

    try:
        target_monday = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await callback.answer()
        return

    is_group_chat = callback.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    user_spec = None
    force_all = ("_all" in raw_payload)

    async with async_session_maker() as session:
        if is_group_chat:
            chat_obj = await session.get(Chat, callback.message.chat.id)
            group_id = chat_obj.group_id if chat_obj else None
        else:
            user = await session.get(User, callback.from_user.id)
            group_id = user.group_id if user else None
            user_spec = user.specialization if (user and not force_all) else None

    if not group_id:
        await callback.answer("Группа не выбрана", show_alert=True)
        return

    group = schedule_cache.get_group_by_id(group_id)
    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return

    actual_monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, target_monday)
    group_title = get_group_display_title(group)

    rich_msg = build_specializations_rich_message(
        group_name=group_title,
        start_monday=actual_monday,
        lessons=lessons,
        target_spec=user_spec
    )

    await callback.answer()

    kb = None
    if user_spec or force_all:
        kb = spec_view_toggle_kb(date_str, group.id, current_is_all=force_all)

    await bot.send_rich_message(chat_id=callback.message.chat.id, rich_message=rich_msg, reply_markup=kb)


@router.message(F.text)
async def handle_schedule_queries(message: Message, state: FSMContext, bot: Bot):
    raw_text = (message.text or "").strip()
    if not raw_text or raw_text.startswith("/") or "Уведы" in raw_text or "Настройки" in raw_text:
        return

    is_group_chat = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    query_text = raw_text

    # 1. В беседах бот реагирует ТОЛЬКО на обращение "Бот ..." (Игнорирует блеблебле, это важно)
    if is_group_chat:
        match_bot = re.match(r"^бот\b(?:[\s,!:—–-]+(.*)|$)", raw_text, re.IGNORECASE)
        if not match_bot:
            return

        extracted_query = match_bot.group(1)
        if not extracted_query or not extracted_query.strip():
            await message.reply("Летаю! 🦅")
            return

        query_text = extracted_query.strip()

        async with async_session_maker() as session:
            chat_obj = await session.get(Chat, message.chat.id)
            if not chat_obj:
                chat_obj = Chat(chat_id=message.chat.id, title=message.chat.title)
                session.add(chat_obj)
                await session.commit()
            elif chat_obj.title != message.chat.title:
                chat_obj.title = message.chat.title
                await session.commit()

            if not chat_obj.is_active:
                return
            chat_group_id = chat_obj.group_id
    else:
        chat_group_id = None

    # 2. Поиск преподавателя (In-Memory O(1))
    now_date = get_minsk_now().date()
    teacher_match = schedule_cache.find_teacher_schedule(query_text, now_date)
    if teacher_match:
        teacher_name, monday, lessons_data = teacher_match
        rich_msg = format_teacher_rich_schedule(
            teacher_full_name=teacher_name,
            start_monday=monday,
            lessons_data=lessons_data
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 3. Парсинг запроса
    parsed = parse_schedule_query(query_text)
    if not parsed:
        return

    await state.clear()

    # 3.1. Запрос свободных аудиторий (НЕ требует привязки к группе)
    if parsed["type"] == "free_rooms":
        if parsed["day_index"] == 6:
            await message.answer("🎉 <b>В воскресенье занятий нет!</b> Все аудитории факультета отдыхают ✨")
            return

        slot_id = parsed.get("slot_id")

        # Сводка на весь день
        if slot_id is None and not parsed.get("is_current"):
            day_data = schedule_cache.find_free_rooms_whole_day(
                target_date=parsed["date"],
                day_index=parsed["day_index"],
                only_potochki=parsed["only_potochki"]
            )
            rich_msg = format_free_rooms_day_summary_rich(
                target_date=parsed["date"],
                day_index=parsed["day_index"],
                data=day_data,
                only_potochki=parsed["only_potochki"]
            )
            await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
            return

        # Запрос на текущую пару ("сейчас")
        if slot_id is None and parsed.get("is_current"):
            slot_id = get_active_slot_id()
            if slot_id is None:
                await message.answer("🌴 <b>Все пары на сегодня уже завершились!</b> Весь корпус свободен ✨")
                return

        # Список на конкретную пару
        free_potochki, free_classrooms = schedule_cache.find_free_rooms(
            target_date=parsed["date"],
            day_index=parsed["day_index"],
            slot_id=slot_id,
            only_potochki=parsed["only_potochki"]
        )

        rich_msg = format_free_rooms_rich_message(
            target_date=parsed["date"],
            day_index=parsed["day_index"],
            slot_id=slot_id,
            free_potochki=free_potochki,
            free_classrooms=free_classrooms,
            only_potochki=parsed["only_potochki"]
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 3.2. Расписание конкретной аудитории
    if parsed["type"] == "room":
        if parsed["day_index"] == 6:
            await message.answer(f"🎉 <b>В воскресенье</b> в <b>{parsed['room_display']}</b> пар нет — корпус закрыт ✨")
            return

        res = schedule_cache.find_room_schedule(parsed["room_query"], parsed["date"])
        if not res:
            await message.answer(f"🌴 В аудитории «<b>{parsed['room_display']}</b>» на этой неделе запланированных пар не найдено (или она свободна)!")
            return

        display_room, actual_monday, room_slots = res
        target_slot = parsed.get("slot_id")
        if parsed.get("is_current"):
            target_slot = get_active_slot_id()

        rich_msg = format_room_rich_schedule(
            room_title=f"{parsed['room_display']} ({display_room})",
            start_monday=actual_monday,
            day_index=parsed["day_index"],
            target_slot=target_slot,
            slots=room_slots
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 4. Определение целевой группы для обычных запросов
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
            await message.answer("⚠️ В этой беседе еще не выбрана группа! Настройте её через <code>/chat_settings</code>")
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

    group_display_title = get_group_display_title(group)

    # 5. Поиск пар по предмету
    if parsed["type"] == "subject":
        target_group_dict = parsed.get("target_group")
        q_course = parsed.get("target_course")
        q_group_num = target_group_dict.get("group_number") if target_group_dict else None

        if not q_course and group:
            q_course = group.course

        subject_match = schedule_cache.find_subject_schedule(
            target_date=parsed["date"],
            canon_subject=parsed["canon_subject"],
            schedule_stems=parsed.get("schedule_stems"),
            raw_word=parsed["raw_subject_word"],
            query_course=q_course,
            query_group_num=q_group_num
        )

        if not subject_match:
            filter_text = f" для группы <b>{q_group_num}</b>" if q_group_num else (f" на <b>{q_course} курсе</b>" if q_course else "")
            await message.answer(f"🌴 На этой неделе пар по предмету «<b>{parsed['canon_subject']}</b>»{filter_text} не найдено!")
            return

        subject_title, actual_monday, subject_slots, filter_badge = subject_match

        rich_msg = format_subject_rich_schedule(
            subject_title=subject_title,
            start_monday=actual_monday,
            lessons_data=subject_slots,
            filter_badge=filter_badge
        )
        await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)
        return

    # 6. Расписание на неделю
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

    # 7. Конкретный слот или текущая пара
    monday, lessons = schedule_cache.get_lessons_for_group(group.id, group.course, parsed["date"])
    day_name = DAYS_NAMES[parsed["day_index"]]
    formatted_date = parsed["date"].strftime("%d.%m")

    if parsed["type"] in ("slot", "current"):
        if parsed["type"] == "current":
            slot_id = get_active_slot_id()
            if slot_id is None:
                await message.answer(f"🌴 <b>{day_name} ({formatted_date})</b> | {group_display_title}\nВсе пары на сегодня уже закончились! Отдыхайте ✨")
                return
        else:
            slot_id = parsed["slot_id"]

        matched = [
            l for l in lessons 
            if l.day == parsed["day_index"] and l.slot_id == slot_id and 
            (l.subgroup is None or l.subgroup == target_subgroup or target_subgroup == 0)
        ]
        matched.sort(key=lambda x: x.subgroup or 0)
        
        slot_info = TIMESLOTS.get(slot_id, {"order": f"{slot_id}️⃣", "time": "--:--"})
        if not matched:
            status = "сейчас нет пар" if parsed["type"] == "current" else f"нет {slot_id}-й пары"
            await message.answer(f"🌴 <b>{day_name} ({formatted_date})</b> | {group_display_title}\nУ вас {status}!")
            return
            
        prefix = f"⚡ <b>Пара ({group_display_title}):</b>\n" if parsed["type"] == "current" else ""
        header = f"{prefix}📍 <b>{day_name} ({formatted_date})</b> | {slot_info['order']} пара\n👥 <b>{group_display_title}</b>\n⏰ <b>{slot_info['time']}</b>\n"

        if len(matched) == 1:
            l = matched[0]
            room_str = f"🚪 <b>ауд. {l.room}</b>" if l.room else "🚪 <i>ауд. ?</i>"
            loc_str = f"{room_str} ⚠️ <b>({l.address}) — ВЫЕЗД!</b>" if l.address and "курчатова" not in l.address.lower() else room_str
            teacher_name = l.teacher if l.teacher else "Преподаватель не указан"
            teacher_str = f"👤 <i>{teacher_name}</i>"
            sub_tag = f" [Подгруппа {l.subgroup}]" if l.subgroup else ""

            text = (
                f"{header}"
                f"📍 {loc_str}\n"
                f"📚 <b>{l.subject} ({l.lesson_type}){sub_tag}</b>\n"
                f"{teacher_str}"
            )
        else:
            items = []
            for idx, l in enumerate(matched, 1):
                room_str = f"🚪 <b>ауд. {l.room}</b>" if l.room else "🚪 <i>ауд. ?</i>"
                loc_str = f"{room_str} ⚠️ <b>({l.address}) — ВЫЕЗД!</b>" if l.address and "курчатова" not in l.address.lower() else room_str
                teacher_name = l.teacher if l.teacher else "Преподаватель не указан"
                sub_badge = f"<b>[{l.subgroup}-я подгруппа]</b>" if l.subgroup else f"<b>[Вариант {idx}]</b>"

                item_text = (
                    f"{sub_badge} | {loc_str}\n"
                    f"📚 <b>{l.subject} ({l.lesson_type})</b>\n"
                    f"👤 <i>{teacher_name}</i>"
                )
                items.append(item_text)

            text = header + "\n" + "\n────────────────────\n".join(items)

        await message.answer(text)
        return

    # 8. Дневная карточка расписания
    rich_msg = build_native_rich_schedule(
        user_name=user_name,
        group_name=group_display_title,
        user_subgroup=target_subgroup,
        day_index=parsed["day_index"],
        target_date=parsed["date"],
        lessons=lessons
    )

    await bot.send_rich_message(chat_id=message.chat.id, rich_message=rich_msg)