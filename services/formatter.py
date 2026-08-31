import re
from datetime import date, timedelta
from collections import defaultdict

from services.dto import LessonDTO, TeacherSlotDTO, SubjectSlotDTO, ScheduleChangeDTO
from aiogram.types import (
    InputRichMessage,
    InputRichBlockSectionHeading,
    InputRichBlockParagraph,
    InputRichBlockDivider,
    InputRichBlockTable,
    RichBlockTableCell,
    RichTextBold,
    RichTextItalic,
    RichTextMarked,
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
        flags=re.IGNORECASE
    ).strip()

    match_initials = re.match(
        r"^([А-ЯЁа-яёA-Za-z\-]+)\s+([А-ЯЁA-Z])\.?\s*([А-ЯЁA-Z])?\.?$",
        name
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

    filtered = [
        l for l in lessons
        if l.day == day_index and (l.subgroup is None or l.subgroup == user_subgroup or user_subgroup == 0)
    ]
    filtered.sort(key=lambda x: (x.slot_id, x.subgroup or 0))

    blocks = [
        InputRichBlockSectionHeading(
            text=RichTextBold(
                text=f"📅 {day_name}, {formatted_date}\n👥 {group_name} • {sub_title}"
            ),
            size=2,
        )
    ]

    if not filtered:
        blocks.append(
            InputRichBlockParagraph(
                text=RichTextItalic(text="🎉 Занятий нет — можно отдыхать! ✨")
            )
        )
        return InputRichMessage(blocks=blocks)

    rows = []
    header_cells = [
        RichBlockTableCell(text=RichTextBold(text="Пара"), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Ауд."), is_header=True, align="center", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Предмет"), is_header=True, align="left", valign="middle"),
        RichBlockTableCell(text=RichTextBold(text="Преподаватель"), is_header=True, align="left", valign="middle"),
    ]
    rows.append(header_cells)

    for l in filtered:
        slot = TIMESLOTS.get(l.slot_id, {"order": str(l.slot_id), "time": "--:--"})
        start_time = slot["time"].split(" - ")[0]

        room_str = l.room or "—"
        if l.address and "курчатова" not in l.address.lower():
            room_str = f"{room_str} ⚠️"

        sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
        type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
        subject_str = f"{l.subject}{type_str}{sub_tag}"
        teacher_str = short_name(l.teacher)

        row_cells = [
            RichBlockTableCell(text=f"{slot['order']} ({start_time})", align="center", valign="middle"),
            RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
            RichBlockTableCell(text=subject_str, align="left", valign="middle"),
            RichBlockTableCell(text=RichTextItalic(text=teacher_str), align="left", valign="middle"),
        ]
        rows.append(row_cells)

    blocks.append(
        InputRichBlockTable(
            cells=rows,
            is_bordered=True,
            is_striped=True,
        )
    )
    return InputRichMessage(blocks=blocks)


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
        day_lessons = [
            l for l in lessons
            if l.day == day_i and (l.subgroup is None or l.subgroup == user_subgroup or user_subgroup == 0)
        ]
        day_lessons.sort(key=lambda x: (x.slot_id, x.subgroup or 0))

        blocks.append(InputRichBlockDivider())
        day_heading = f"▫️ {DAYS_NAMES[day_i]} ({day_date.strftime('%d.%m')})"

        if not day_lessons:
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

        for l in day_lessons:
            slot = TIMESLOTS.get(l.slot_id, {"order": str(l.slot_id), "time": "--:--"})
            start_time = slot["time"].split(" - ")[0]

            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
            teacher_str = short_name(l.teacher)

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({start_time})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=f"{l.subject}{type_str}{sub_tag}", align="left", valign="middle"),
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
        )
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
            start_time = slot["time"].split(" - ")[0]

            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
            groups_str = l.groups_display

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({start_time})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=groups_str, align="center", valign="middle"),
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
        )
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
            start_time = slot["time"].split(" - ")[0]

            room_str = l.room or "—"
            if l.address and "курчатова" not in l.address.lower():
                room_str = f"{room_str} ⚠️"

            sub_tag = f" (п/г {l.subgroup})" if l.subgroup else ""
            type_str = f" [{l.lesson_type}]" if l.lesson_type else ""
            groups_str = l.groups_display
            teacher_str = short_name(l.teacher)

            rows.append([
                RichBlockTableCell(text=f"{slot['order']} ({start_time})", align="center", valign="middle"),
                RichBlockTableCell(text=RichTextBold(text=room_str), align="center", valign="middle"),
                RichBlockTableCell(text=groups_str, align="center", valign="middle"),
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
        )
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