import re
from datetime import date, timedelta
from collections import defaultdict
from typing import Any

from services.dto import (
    LessonDTO,
    RoomSlotDTO,
    TeacherSlotDTO,
    SubjectSlotDTO,
    ScheduleChangeDTO,
)
from aiogram.types import (
    InputRichMessage,
    InputRichBlockSectionHeading,
    InputRichBlockParagraph,
    InputRichBlockDivider,
    InputRichBlockTable,
    RichBlockTableCell,
    RichTextBold,
    RichTextItalic,
    RichTextStrikethrough,
)

TIMESLOTS = {
    1: {"order": "1", "time": "09:00 - 10:25"},
    2: {"order": "2", "time": "10:35 - 12:00"},
    3: {"order": "3", "time": "12:10 - 13:35"},
    4: {"order": "4", "time": "14:00 - 15:25"},
    5: {"order": "5", "time": "15:35 - 17:00"},
    6: {"order": "6", "time": "17:10 - 18:35"},
    7: {"order": "7", "time": "18:45 - 20:10"},
    8: {"order": "8", "time": "20:30 - 21:55"},
}

DAYS_NAMES = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def clean_html(raw_text: str | None) -> str:
    if not raw_text:
        return ""
    return re.sub(r"<[^>]+>", "", str(raw_text)).strip()


def short_name(full_name: str | None) -> str:
    if not full_name:
        return "—"

    name = full_name.strip()
    name = re.sub(
        r"^(?:(?:ст\.\s*)?преп\.?|доц\.?|проф\.?|ассист\.?|акад\.?)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()

    match_initials = re.match(
        r"^([А-ЯЁа-яёA-Za-z\-]+)\s+([А-ЯЁA-Z])\.?\s*([А-ЯЁA-Z])?\.?$",
        name,
    )
    if match_initials:
        surname = match_initials.group(1).capitalize()
        init1 = match_initials.group(2).upper()
        init2 = match_initials.group(3).upper() if match_initials.group(3) else ""
        if init2:
            return f"{surname} {init1}.{init2}."
        return f"{surname} {init1}."

    parts = name.split()
    if len(parts) >= 3:
        surname = parts[0].capitalize()
        init1 = parts[1][0].upper()
        init2 = parts[2][0].upper()
        return f"{surname} {init1}.{init2}."
    elif len(parts) == 2:
        surname = parts[0].capitalize()
        sub_inits = re.findall(r"[А-ЯЁA-Za-z]", parts[1])
        if len(sub_inits) >= 2:
            return f"{surname} {sub_inits[0].upper()}.{sub_inits[1].upper()}."
        elif len(sub_inits) == 1:
            return f"{surname} {sub_inits[0].upper()}."
        return f"{surname} {parts[1][0].upper()}."

    return name


def _collapse_day_lessons(lessons: list[LessonDTO], user_subgroup: int = 0) -> list[dict]:
    filtered = [
        l for l in lessons
        if (l.subgroup is None or l.subgroup == user_subgroup or user_subgroup == 0)
    ]

    by_slot: dict[int, list[LessonDTO]] = defaultdict(list)
    for l in filtered:
        by_slot[l.slot_id].append(l)

    result_rows = []
    for slot_id in sorted(by_slot.keys()):
        slot_lessons = by_slot[slot_id]

        spec_lessons = [l for l in slot_lessons if l.specialization_order is not None]

        if len(spec_lessons) > 1:
            common_title = next(
                (l.common_discipline for l in spec_lessons if l.common_discipline),
                "Спецпрактикум (дисциплины профилизации)"
            )
            l_type = spec_lessons[0].lesson_type or "ЛР"
            result_rows.append({
                "slot_id": slot_id,
                "room": "Кафедры",
                "subject": f"{common_title} [{l_type}]",
                "teacher": "См. кнопку 🧬",
                "subgroup": None
            })

            for l in slot_lessons:
                if l.specialization_order is None:
                    result_rows.append({
                        "slot_id": slot_id,
                        "room": l.room or "—",
                        "subject": f"{l.subject} [{l.lesson_type}]" if l.lesson_type else l.subject,
                        "teacher": short_name(l.teacher),
                        "subgroup": l.subgroup
                    })
        else:
            for l in slot_lessons:
                sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
                type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
                room_str = l.room or "—"
                if l.address and "курчатова" not in l.address.lower():
                    room_str = f"{room_str} ⚠️"

                result_rows.append({
                    "slot_id": slot_id,
                    "room": room_str,
                    "subject": f"{l.subject}{type_str}{sub_tag}",
                    "teacher": short_name(l.teacher),
                    "subgroup": l.subgroup
                })

    result_rows.sort(key=lambda x: (x["slot_id"], x["subgroup"] or 0))
    return result_rows


# 1. Расписание на один день (карточка)
def build_native_rich_schedule(
    user_name: str,
    group_name: str,
    user_subgroup: int,
    day_index: int,
    target_date: date,
    lessons: list[LessonDTO],
) -> InputRichMessage:
    day_name = DAYS_NAMES[day_index]
    formatted_date = target_date.strftime("%d.%m.%Y")
    sub_title = f"{user_subgroup} п/г" if user_subgroup else "Вся группа"

    day_lessons = [l for l in lessons if l.day == day_index]
    display_items = _collapse_day_lessons(day_lessons, user_subgroup)

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"📅 {day_name}, {formatted_date}\n👥 {group_name} • {sub_title}"
            ),
            size=2,
        )
    ]

    if not display_items:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="🎉 Занятий нет — можно отдыхать! ✨")
            )
        )
        return InputRichMessage(blocks=blocks)

    rows = [[
        RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Предмет"), is_header=True, align="left", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
    ]]

    for item in display_items:
        slot = TIMESLOTS.get(item["slot_id"], {"order": str(item["slot_id"]), "time": "--:--"})
        time_interval = slot["time"].replace(" - ", "–")

        rows.append([
            RichBlockTableCell(text=f"{slot['order']} ({time_interval})", align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text=item["room"]), align="center", valign="middle"),
            RichBlockTableCell(text=item["subject"], align="left", valign="middle"),
            RichBlockTableCell(text=RichTextItalic(text=item["teacher"]), align="left", valign="middle"),
        ])

    blocks.append(
        InputRichBlockTable(
            cells=rows,
            is_bordered=True,
            is_striped=True,
        )
    )
    return InputRichMessage(blocks=blocks)


# 2. Расписание на неделю
def format_full_week_rich_message(
    user_name: str,
    group_name: str,
    user_subgroup: int,
    start_monday: date,
    lessons: list[LessonDTO],
) -> InputRichMessage:
    sub_title = f"{user_subgroup} п/г" if user_subgroup else "Вся группа"
    end_saturday = start_monday + timedelta(days=5)

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"🗓 Расписание: {start_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}\n👥 {group_name} • {sub_title}"
            ),
            size=2,
        )
    ]

    for day_i in range(6):
        day_date = start_monday + timedelta(days=day_i)
        day_lessons = [l for l in lessons if l.day == day_i]
        display_items = _collapse_day_lessons(day_lessons, user_subgroup)

        blocks.append(InputRichBlockDivider())
        day_heading = f"▫️ {DAYS_NAMES[day_i]} ({day_date.strftime('%d.%m')})"

        if not display_items:
            blocks.append(
                InputRichBlockParagraph(
                    text=RichTextItalic(text=f"{day_heading} — пар нет 🌴")
                )
            )
            continue

        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(text=day_heading)
            )
        )

        rows = [[
            RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Предмет"), is_header=True, align="left", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
        ]]

        for item in display_items:
            slot = TIMESLOTS.get(item["slot_id"], {"order": str(item["slot_id"]), "time": "--:--"})
            time_interval = slot["time"].replace(" - ", "–")

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({time_interval})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=item["room"]), align="center", valign="middle"),
                RichBlockTableCell(text=item["subject"], align="left", valign="middle"),
                RichBlockTableCell(text=RichTextItalic(text=item["teacher"]), align="left", valign="middle"),
            ])

        
        blocks.append(
            InputRichBlockTable(
                cells=rows,
                is_bordered=True,
                is_striped=True,
            )
        )

    return InputRichMessage(blocks=blocks)


# 3. Расписание преподавателя
def format_teacher_rich_schedule(
    teacher_full_name: str,
    start_monday: date,
    lessons_data: list[TeacherSlotDTO],
) -> InputRichMessage:
    end_saturday = start_monday + timedelta(days=5)

    unique_subjects = sorted(list({item.subject for item in lessons_data}))
    subjects_text = ", ".join(unique_subjects) if unique_subjects else "Не указаны"

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"👨‍🏫 {teacher_full_name}\n🗓 Неделя: {start_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}"
            ),
            size=2,
        ),
        InputRichBlockParagraph(
            text=RichTextItalic(text=f"📚 Дисциплины: {subjects_text}")
        ),
    ]

    if not lessons_data:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="На этой неделе запланированных пар нет 🌴")
            )
        )
        return InputRichMessage(blocks=blocks)

    for day_i in range(6):
        day_date = start_monday + timedelta(days=day_i)
        day_lessons = [item for item in lessons_data if item.day == day_i]
        day_lessons.sort(key=lambda x: x.slot_id)

        blocks.append(InputRichBlockDivider())
        day_heading = f"▫️ {DAYS_NAMES[day_i]} ({day_date.strftime('%d.%m')})"

        if not day_lessons:
            blocks.append(
                InputRichBlockParagraph(
                    text=RichTextItalic(text=f"{day_heading} — пар нет")
                )
            )
            continue

        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(text=day_heading)
            )
        )

        rows = [[
            RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Группа"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Предмет"), is_header=True, align="left", valign="middle"),
        ]]

        for l in day_lessons:
            slot = TIMESLOTS.get(l.slot_id, {"order": str(l.slot_id), "time": "--:--"})
            time_interval = slot["time"].replace(" - ", "–")

            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({time_interval})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=l.groups_display, align="center", valign="middle"),
                RichBlockTableCell(text=f"{l.subject}{type_str}{sub_tag}", align="left", valign="middle"),
            ])

        blocks.append(
            InputRichBlockTable(
                cells=rows,
                is_bordered=True,
                is_striped=True,
            )
        )

    return InputRichMessage(blocks=blocks)


# 4. Расписание предмета
def format_subject_rich_schedule(
    subject_title: str,
    start_monday: date,
    lessons_data: list[SubjectSlotDTO],
    filter_badge: str | None = None,
) -> InputRichMessage:
    end_saturday = start_monday + timedelta(days=5)

    unique_teachers = sorted(list({short_name(item.teacher) for item in lessons_data if item.teacher}))
    teachers_text = ", ".join(unique_teachers) if unique_teachers else "Не указан"

    badge_line = f"\n{filter_badge}" if filter_badge else ""

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"📚 {subject_title}{badge_line}\n🗓 Неделя: {start_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}"
            ),
            size=2,
        ),
        InputRichBlockParagraph(
            text=RichTextItalic(text=f"👨‍🏫 Преподаватели: {teachers_text}")
        ),
    ]

    if not lessons_data:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="На этой неделе запланированных пар по этой дисциплине нет 🌴")
            )
        )
        return InputRichMessage(blocks=blocks)

    for day_i in range(6):
        day_date = start_monday + timedelta(days=day_i)
        day_lessons = [item for item in lessons_data if item.day == day_i]
        day_lessons.sort(key=lambda x: (x.slot_id, x.subgroup or 0))

        blocks.append(InputRichBlockDivider())
        day_heading = f"▫️ {DAYS_NAMES[day_i]} ({day_date.strftime('%d.%m')})"

        if not day_lessons:
            blocks.append(
                InputRichBlockParagraph(
                    text=RichTextItalic(text=f"{day_heading} — пар нет")
                )
            )
            continue

        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(text=day_heading)
            )
        )

        rows = [[
            RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Группа"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
        ]]

        for l in day_lessons:
            slot = TIMESLOTS.get(l.slot_id, {"order": str(l.slot_id), "time": "--:--"})
            time_interval = slot["time"].replace(" - ", "–")

            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
            teacher_str = short_name(l.teacher)

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({time_interval})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=l.groups_display, align="center", valign="middle"),
                RichBlockTableCell(text=f"{teacher_str}{type_str}{sub_tag}", align="left", valign="middle"),
            ])

        blocks.append(
            InputRichBlockTable(
                cells=rows,
                is_bordered=True,
                is_striped=True,
            )
        )

    return InputRichMessage(blocks=blocks)


# 5. Оповещения об изменениях в расписании
def build_schedule_changes_rich_message(
    group_name: str,
    start_monday: date,
    changes: list[ScheduleChangeDTO],
) -> InputRichMessage:
    end_saturday = start_monday + timedelta(days=5)

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"⚠️ ИЗМЕНЕНИЯ В РАСПИСАНИИ!\n👥 {group_name} • {start_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}"
            ),
            size=2,
        ),
        InputRichBlockParagraph(
            text=RichTextItalic(
                text="Сайт bio.bsu.by обновил расписание вашей группы:"
            )
        ),
    ]

    by_days = defaultdict(list)
    for ch in changes:
        by_days[ch.day].append(ch)

    for day_i in sorted(by_days.keys()):
        day_date = start_monday + timedelta(days=day_i)
        day_changes = by_days[day_i]
        day_changes.sort(key=lambda x: (x.slot_id, x.subgroup or 0))

        blocks.append(InputRichBlockDivider())
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(text=f"📍 {DAYS_NAMES[day_i]} ({day_date.strftime('%d.%m')})")
            )
        )

        for ch in day_changes:
            slot_info = TIMESLOTS.get(ch.slot_id, {"order": str(ch.slot_id), "time": "--:--"})
            start_time = slot_info["time"].split(" - ")[0]
            sub_str = f" [п/г {ch.subgroup}]" if ch.subgroup else ""
            type_str = f" [{ch.lesson_type}]" if ch.lesson_type else ""

            clean_subj = clean_html(ch.subject)
            room_text = f"🚪 ауд. {ch.room}" if ch.room else "🚪 ауд. —"

            if ch.change_type == "added":
                details_clean = [clean_html(d) for d in ch.details]
                det_text = f" ({', '.join(details_clean)})" if details_clean else ""
                teacher_text = f"\n👤 Преподаватель: {short_name(ch.teacher)}" if ch.teacher else ""

                card_text = (
                    f"🟢 {slot_info['order']} пара ({start_time}) | {room_text}\n"
                    f"📚 {clean_subj}{type_str}{sub_str}\n"
                    f"➕ Добавлена новая пара{det_text}{teacher_text}"
                )
                blocks.append(InputRichBlockParagraph(text=RichTextBold(text=card_text)))

            elif ch.change_type == "removed":
                card_text = (
                    f"🔴 {slot_info['order']} пара ({start_time}) | ауд. {ch.room or '—'}\n"
                    f"📚 {clean_subj}{type_str}{sub_str}\n"
                    f"❌ Пара отменена!"
                )
                blocks.append(InputRichBlockParagraph(text=RichTextStrikethrough(text=card_text)))

            else:
                diffs_clean = [clean_html(d) for d in ch.details]
                diffs_text = f"\n🔄 Изменения: {', '.join(diffs_clean)}" if diffs_clean else ""
                teacher_text = f"\n👤 Преподаватель: {short_name(ch.teacher)}" if ch.teacher else ""

                card_text = (
                    f"🟡 {slot_info['order']} пара ({start_time}) | {room_text}\n"
                    f"📚 {clean_subj}{type_str}{sub_str}"
                    f"{diffs_text}{teacher_text}"
                )
                blocks.append(InputRichBlockParagraph(text=RichTextBold(text=card_text)))

    return InputRichMessage(blocks=blocks)


# 6. Профилизации и спецкурсы
def build_specializations_rich_message(
    group_name: str,
    start_monday: date,
    lessons: list[LessonDTO],
    target_spec: int | None = None,
) -> InputRichMessage:
    end_saturday = start_monday + timedelta(days=5)

    spec_lessons = [
        l for l in lessons
        if l.specialization_order is not None or (l.common_discipline and not l.subgroup)
    ]

    title_suffix = f" • Направление #{target_spec}" if target_spec else ""
    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"🧬 Профилизации и спецкурсы{title_suffix}\n👥 {group_name} • {start_monday.strftime('%d.%m')} — {end_saturday.strftime('%d.%m')}"
            ),
            size=2,
        )
    ]

    if not spec_lessons:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="На этой неделе профилизаций и спецкурсов нет ✨")
            )
        )
        return InputRichMessage(blocks=blocks)

    slots_map = defaultdict(list)
    for l in spec_lessons:
        slots_map[(l.day, l.slot_id)].append(l)

    for (day_i, slot_id) in sorted(slots_map.keys(), key=lambda x: (x[0], x[1])):
        day_date = start_monday + timedelta(days=day_i)
        day_name = DAYS_NAMES[day_i]
        slot_info = TIMESLOTS.get(slot_id, {"order": str(slot_id), "time": "--:--"})

        slot_items = slots_map[(day_i, slot_id)]
        slot_items.sort(key=lambda x: x.specialization_order or 0)

        if target_spec:
            user_filtered = [l for l in slot_items if l.specialization_order == target_spec]
            if user_filtered:
                slot_items = user_filtered

        common_name = next(
            (l.common_discipline for l in slot_items if l.common_discipline),
            "Спецпрактикум (дисциплины профилизации)"
        )

        blocks.append(InputRichBlockDivider())
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(
                    text=f"📍 {day_name} ({day_date.strftime('%d.%m')}), {slot_info['order']} пара ({slot_info['time']})\n📚 {common_name}"
                )
            )
        )

        rows = [[
            RichBlockTableCell(text=RichTextBold(text="№"), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Кафедра / Дисциплина"), is_header=True, align="left", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
        ]]

        for l in slot_items:
            order_label = f"#{l.specialization_order}" if l.specialization_order else "•"
            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
            teacher_str = short_name(l.teacher)

            rows.append([
                RichBlockTableCell(text=order_label, align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=f"{l.subject}{type_str}", align="left", valign="middle"),
                RichBlockTableCell(text=RichTextItalic(text=teacher_str), align="left", valign="middle"),
            ])

        blocks.append(
            InputRichBlockTable(
                cells=rows,
                is_bordered=True,
                is_striped=True,
            )
        )

    return InputRichMessage(blocks=blocks)


# 7. Сводка свободных аудиторий на весь день
def format_free_rooms_day_summary_rich(
    target_date: date,
    day_index: int,
    data: dict[str, Any],
    only_potochki: bool = False,
) -> InputRichMessage:
    day_name = DAYS_NAMES[day_index]
    formatted_date = target_date.strftime("%d.%m.%Y")

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"🟢 Свободные аудитории на весь день\n📅 {day_name}, {formatted_date}"
            ),
            size=2,
        )
    ]

    if data.get("all_day_free") and not only_potochki:
        free_all_str = " • ".join(data["all_day_free"][:12])
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(
                    text=f"✨ Свободны ВЕСЬ ДЕНЬ (1–6 пары):\n👉 {free_all_str}"
                )
            )
        )
        blocks.append(InputRichBlockDivider())

    for s in data.get("slots_summary", []):
        slot_info = TIMESLOTS.get(s["slot_id"], {"order": str(s["slot_id"]), "time": "--:--"})
        pot_str = ", ".join(s["free_potochki"]) if s["free_potochki"] else "все заняты 🔒"

        line_text = f"📍 {slot_info['order']} пара ({slot_info['time']})\n🏛 Поточки: {pot_str}"
        if not only_potochki:
            cls_cnt = s["free_classrooms_count"]
            line_text += f"\n🚪 Свободных кабинетов: {cls_cnt} шт."

        blocks.append(InputRichBlockParagraph(text=line_text))

    blocks.append(InputRichBlockDivider())
    blocks.append(
        InputRichBlockParagraph(
            text=RichTextItalic(
                text="💡 Чтобы увидеть полный список кабинетов на конкретную пару, спросите: «свободные во вторник на 3 паре»"
            )
        )
    )

    return InputRichMessage(blocks=blocks)


# 8. Расписание конкретной аудитории
def format_room_rich_schedule(
    room_title: str,
    start_monday: date,
    day_index: int,
    target_slot: int | None,
    slots: list[RoomSlotDTO],
) -> InputRichMessage:
    day_name = DAYS_NAMES[day_index]
    target_date = start_monday + timedelta(days=day_index)
    formatted_date = target_date.strftime("%d.%m.%Y")

    day_slots = [s for s in slots if s.day == day_index]
    if target_slot is not None:
        day_slots = [s for s in day_slots if s.slot_id == target_slot]

    day_slots.sort(key=lambda x: x.slot_id)

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"🚪 {room_title}\n📅 {day_name}, {formatted_date}"
            ),
            size=2,
        )
    ]

    if not day_slots:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="🎉 В это время аудитория свободна! Можно спокойно заниматься ✨")
            )
        )
        return InputRichMessage(blocks=blocks)

    rows = [[
        RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Группа"), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Предмет"), is_header=True, align="left", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
    ]]

    for s in day_slots:
        slot_info = TIMESLOTS.get(s.slot_id, {"order": str(s.slot_id), "time": "--:--"})
        start_time = slot_info["time"].split(" - ")[0]
        type_str = f" [{s.lesson_type}]" if s.lesson_type else ""
        teacher_str = short_name(s.teacher)

        rows.append([
            RichBlockTableCell(text=f"{slot_info['order']} ({start_time})", align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text=s.groups_display), align="center", valign="middle"),
            RichBlockTableCell(text=f"{s.subject}{type_str}", align="left", valign="middle"),
            RichBlockTableCell(text=RichTextItalic(text=teacher_str), align="left", valign="middle"),
        ])

    blocks.append(
        InputRichBlockTable(
            cells=rows,
            is_bordered=True,
            is_striped=True,
        )
    )

    return InputRichMessage(blocks=blocks)


# 9. Свободные аудитории на одну пару
def format_free_rooms_rich_message(
    target_date: date,
    day_index: int,
    slot_id: int,
    free_potochki: list[str],
    free_classrooms: list[str],
    only_potochki: bool = False,
) -> InputRichMessage:
    day_name = DAYS_NAMES[day_index]
    formatted_date = target_date.strftime("%d.%m.%Y")
    slot_info = TIMESLOTS.get(slot_id, {"order": str(slot_id), "time": "--:--"})

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"🟢 Свободные аудитории\n📅 {day_name}, {formatted_date} • {slot_info['order']} пара ({slot_info['time']})"
            ),
            size=2,
        )
    ]

    if free_potochki:
        p_text = " • ".join(free_potochki)
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextBold(text=f"🏛 Свободные поточки:\n👉 {p_text}")
            )
        )
    else:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="🏛 Поточные аудитории: все заняты 🔒")
            )
        )

    if not only_potochki:
        blocks.append(InputRichBlockDivider())
        if free_classrooms:
            chunks = [free_classrooms[i:i + 6] for i in range(0, len(free_classrooms), 6)]
            formatted_chunks = "\n".join([" • ".join(ch) for ch in chunks])
            blocks.append(
                InputRichBlockParagraph(
                    text=f"🚪 Свободные кабинеты и лаборатории:\n{formatted_chunks}"
                )
            )
        else:
            blocks.append(
                InputRichBlockParagraph(
                    text=RichTextItalic(text="🚪 Учебные кабинеты: свободных не найдено")
                )
            )

    return InputRichMessage(blocks=blocks)

# Ну и говнище тут всё