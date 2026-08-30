import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Group, Week, Lesson
from services.dto import GroupDTO, WeekDTO, LessonDTO, TeacherSlotDTO
from config import logger

TEACHER_STOP_WORDS = {
    "где",
    "препод",
    "преподаватель",
    "препода",
    "преподавателя",
    "преподавателю",
    "пары",
    "пара",
    "пару",
    "паре",
    "парой",
    "парам",
    "парами",
    "парах",
    "расписание",
    "расписанию",
    "расписанием",
    "расписании",
    "неделя",
    "неделю",
    "неделе",
    "неделей",
    "недели",
    "на",
    "в",
    "во",
    "у",
    "к",
    "с",
    "со",
    "от",
    "до",
    "по",
    "о",
    "об",
    "за",
    "из",
    "какая",
    "какой",
    "какие",
    "каком",
    "какую",
    "что",
    "когда",
    "кто",
    "кем",
    "кому",
    "след",
    "следующая",
    "следующую",
    "следующей",
    "следующий",
    "будет",
    "были",
    "было",
    "завтра",
    "сегодня",
    "послезавтра",
    "вчера",
    "сейчас",
    "пн",
    "вт",
    "ср",
    "чт",
    "пт",
    "сб",
    "вс",
    "курс",
    "курса",
    "курсе",
    "курсу",
    "группа",
    "группы",
    "группе",
    "группу",
    "группой",
    "ауд",
    "аудитория",
    "аудитории",
    "аудиторию",
    "корпус",
    "корпусе",
    "подгруппа",
    "подгруппы",
    "подгруппе",
    "подгруппу",
    "там",
    "тут",
    "здесь",
    "туда",
    "сюда",
    "куда",
    "откуда",
    "привет",
    "хай",
    "ку",
    "скиньте",
    "лаба",
    "лабу",
    "дз",
    "лекция",
    "лекции",
}


def _match_teacher_surname(query_word: str, full_teacher_name: str) -> bool:
    parts = full_teacher_name.strip().split()
    if not parts:
        return False

    # Ищем ТОЛЬКО по фамилии (первое слово ФИО)
    surname = parts[0].lower()
    q = query_word.lower()

    if len(q) < 3 or len(surname) < 3:
        return False

    # 1. Точное совпадение
    if q == surname:
        return True

    # 2. Если слово 3 буквы — только точное совпадение (защита от "там", "сам", "кто")
    if len(q) == 3 or len(surname) == 3:
        return q == surname

    # 3. Для слов от 4 букв — поиск общего префикса (корня)
    # Находим длину совпадающей начальной части слова
    common_len = 0
    min_l = min(len(q), len(surname))
    while common_len < min_l and q[common_len] == surname[common_len]:
        common_len += 1

    # Корень должен быть не менее 4 символов и покрывать почти всю фамилию (допуская смену окончания 1-3 буквы)
    if common_len >= 4 and common_len >= (len(surname) - 3) and common_len >= (len(q) - 3):
        return True

    return False


class ScheduleCache:
    def __init__(self) -> None:
        self._groups_by_id: dict[int, GroupDTO] = {}
        self._groups_by_course_num: dict[tuple[int, str], GroupDTO] = {}
        self._weeks_by_course: dict[int, list[WeekDTO]] = {}
        self._lessons_by_group_week: dict[tuple[int, int], list[LessonDTO]] = {}
        self._teacher_records: dict[str, list[tuple[LessonDTO, GroupDTO, WeekDTO]]] = {}
        self._teachers_list: list[str] = []
        self._is_ready: bool = False

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    def get_cache_stats(self) -> dict[str, Any]:
        total_lessons = sum(len(v) for v in self._lessons_by_group_week.values())
        total_weeks = sum(len(v) for v in self._weeks_by_course.values())
        return {
            "is_ready": self._is_ready,
            "groups_count": len(self._groups_by_id),
            "weeks_count": total_weeks,
            "lessons_count": total_lessons,
            "teachers_count": len(self._teachers_list),
        }

    async def reload_from_db(self, session: AsyncSession) -> None:
        logger.info("🧠 [Cache] Загрузка данных из БД в In-Memory кэш...")

        # 1. Загрузка групп
        groups_res = await session.execute(select(Group))
        db_groups = groups_res.scalars().all()

        new_groups_by_id: dict[int, GroupDTO] = {}
        new_groups_by_course_num: dict[tuple[int, str], GroupDTO] = {}

        for g in db_groups:
            clean_num = str(g.number).strip()
            dto = GroupDTO(
                id=g.id, course=g.course, number=clean_num, name=g.name, study_mode=g.study_mode or "Дневная"
            )
            new_groups_by_id[g.id] = dto
            new_groups_by_course_num[(g.course, clean_num)] = dto

        # 2. Загрузка недель
        weeks_res = await session.execute(select(Week).order_by(Week.start_date.desc()))
        db_weeks = weeks_res.scalars().all()

        new_weeks_by_id: dict[int, WeekDTO] = {}
        new_weeks_by_course: dict[int, list[WeekDTO]] = defaultdict(list)

        for w in db_weeks:
            dto = WeekDTO(id=w.id, course=w.course, start_date=w.start_date, study_mode=w.study_mode or "Дневная")
            new_weeks_by_id[w.id] = dto
            new_weeks_by_course[w.course].append(dto)

        # 3. Загрузка занятий
        lessons_res = await session.execute(select(Lesson))
        db_lessons = lessons_res.scalars().all()

        new_lessons_by_group_week: dict[tuple[int, int], list[LessonDTO]] = defaultdict(list)
        new_teacher_records: dict[str, list[tuple[LessonDTO, GroupDTO, WeekDTO]]] = defaultdict(list)
        new_teachers_set: set[str] = set()

        for l in db_lessons:
            lesson_dto = LessonDTO(
                id=l.id,
                group_id=l.group_id,
                week_id=l.week_id,
                day=l.day,
                slot_id=l.slot_id,
                subject=l.subject,
                lesson_type=l.lesson_type,
                teacher=l.teacher,
                room=l.room,
                address=l.address,
                subgroup=l.subgroup,
            )
            new_lessons_by_group_week[(l.group_id, l.week_id)].append(lesson_dto)

            if l.teacher:
                teacher_clean = l.teacher.strip()
                new_teachers_set.add(teacher_clean)
                group_dto = new_groups_by_id.get(l.group_id)
                week_dto = new_weeks_by_id.get(l.week_id)
                if group_dto and week_dto:
                    new_teacher_records[teacher_clean].append((lesson_dto, group_dto, week_dto))

        # 4. Атомарная подмена ссылок
        self._groups_by_id = new_groups_by_id
        self._groups_by_course_num = new_groups_by_course_num
        self._weeks_by_course = dict(new_weeks_by_course)
        self._lessons_by_group_week = dict(new_lessons_by_group_week)
        self._teacher_records = dict(new_teacher_records)
        self._teachers_list = sorted(list(new_teachers_set))
        self._is_ready = True

        logger.info(
            f"✨ [Cache] Кэш готов: {len(self._groups_by_id)} групп, "
            f"{len(db_lessons)} пар, {len(self._teachers_list)} преподавателей."
        )

    # ==========================================
    # Быстрые методы чтения O(1)
    # ==========================================

    def get_group_by_id(self, group_id: int) -> GroupDTO | None:
        return self._groups_by_id.get(group_id)

    def find_group_by_course_and_number(self, course: int, number: str | int) -> GroupDTO | None:
        clean_num = str(number).strip()
        return self._groups_by_course_num.get((course, clean_num))

    def get_all_groups_for_course(self, course: int) -> list[GroupDTO]:
        groups = [g for g in self._groups_by_id.values() if g.course == course]
        groups.sort(key=lambda g: int(g.number) if g.number.isdigit() else 999)
        return groups

    def get_all_teachers(self) -> list[str]:
        return self._teachers_list

    def get_lessons_for_group(self, group_id: int, course: int, target_date: date) -> tuple[date, list[LessonDTO]]:
        monday = target_date - timedelta(days=target_date.weekday())
        weeks = self._weeks_by_course.get(course, [])

        target_week = next((w for w in weeks if w.start_date == monday), None)

        if not target_week:
            for w in weeks:
                if (group_id, w.id) in self._lessons_by_group_week:
                    target_week = w
                    break

        if not target_week:
            return monday, []

        lessons = self._lessons_by_group_week.get((group_id, target_week.id), [])
        return target_week.start_date, lessons

    def find_teacher_schedule(
        self, query_text: str, target_date: date
    ) -> tuple[str, date, list[TeacherSlotDTO]] | None:
        clean = re.sub(r"[^\w\s-]", " ", query_text.lower())
        words = [w for w in clean.split() if w not in TEACHER_STOP_WORDS and len(w) >= 3]
        if not words or not self._teachers_list:
            return None

        matched_teacher: str | None = None
        for word in words:
            for t in self._teachers_list:
                if _match_teacher_surname(word, t):
                    matched_teacher = t
                    break
            if matched_teacher:
                break

        if not matched_teacher:
            return None

        records = self._teacher_records.get(matched_teacher, [])
        if not records:
            return None

        monday = target_date - timedelta(days=target_date.weekday())

        target_records = [r for r in records if r[2].start_date == monday]
        actual_monday = monday

        if not target_records:
            available_mondays = sorted(list({r[2].start_date for r in records}), reverse=True)
            if available_mondays:
                actual_monday = available_mondays[0]
                target_records = [r for r in records if r[2].start_date == actual_monday]

        if not target_records:
            return None

        grouped_slots: dict[tuple, TeacherSlotDTO] = {}
        for lesson, group, week in target_records:
            g_tag = f"{group.course}-{group.number}" if group else "?"
            key = (lesson.day, lesson.slot_id, lesson.subject, lesson.lesson_type, lesson.room)

            if key not in grouped_slots:
                grouped_slots[key] = TeacherSlotDTO(
                    day=lesson.day,
                    slot_id=lesson.slot_id,
                    subject=lesson.subject,
                    lesson_type=lesson.lesson_type,
                    room=lesson.room,
                    address=lesson.address,
                    subgroup=lesson.subgroup,
                    groups=[g_tag],
                )
            else:
                if g_tag not in grouped_slots[key].groups:
                    grouped_slots[key].groups.append(g_tag)

        lessons_list: list[TeacherSlotDTO] = []
        for item in grouped_slots.values():
            item.groups_display = ", ".join(item.groups)
            lessons_list.append(item)

        return matched_teacher, actual_monday, lessons_list


schedule_cache = ScheduleCache()
