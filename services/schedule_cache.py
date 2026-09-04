import re
from collections import defaultdict, Counter
from datetime import date, timedelta
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Group, Week, Lesson
from services.dto import GroupDTO, WeekDTO, LessonDTO, TeacherSlotDTO, SubjectSlotDTO, RoomSlotDTO
from services.subject_dict import SUBJECT_REGISTRY
from config import logger

TEACHER_STOP_WORDS = {
    "где", "препод", "преподаватель", "препода", "преподавателя", "преподавателю",
    "пары", "пара", "пару", "паре", "парой", "парам", "парами", "парах",
    "расписание", "расписанию", "расписанием", "расписании",
    "неделя", "неделю", "неделе", "неделей", "недели",
    "на", "в", "во", "у", "к", "с", "со", "от", "до", "по", "о", "об", "за", "из",
    "какая", "какой", "какие", "каком", "какую", "что", "когда", "кто", "кем", "кому",
    "след", "следующая", "следующую", "следующей", "следующий", "будет", "были", "было",
    "завтра", "сегодня", "послезавтра", "вчера", "сейчас",
    "пн", "вт", "ср", "чт", "пт", "сб", "вс",
    "курс", "курса", "курсе", "курсу",
    "группа", "группы", "группе", "группу", "группой",
    "ауд", "аудитория", "аудитории", "аудиторию", "корпус", "корпусе",
    "подгруппа", "подгруппы", "подгруппе", "подгруппу",
    "там", "тут", "здесь", "туда", "сюда", "куда", "откуда",
    "привет", "хай", "ку", "скиньте", "лаба", "лабу", "дз", "лекция", "лекции"
}

KNOWN_POTOCHKI = ["1 п.а.", "2 п.а.", "3 п.а."]


# Разбор профиля преподавателя из базы
def parse_teacher_profile(full_name: str) -> dict[str, Any]:
    clean = re.sub(
        r"^(?:(?:ст\.\s*)?преп\.?|доц\.?|проф\.?|ассист\.?|акад\.?)\s+",
        "",
        full_name.strip(),
        flags=re.IGNORECASE
    ).strip()

    parts = clean.split()
    surname_raw = parts[0] if parts else clean
    surname = re.sub(r"[^\w\-]", "", surname_raw).lower()

    # Сбор инициалов
    initials = []
    for p in parts[1:]:
        inits = re.findall(r"([а-яёa-z])\.?", p.lower())
        for char in inits:
            if char.isalpha():
                initials.append(char)

    gender = "m"
    stem = surname

    if surname.endswith(("ова", "ева", "ёва", "ина", "ына")):
        gender = "f"
        stem = surname[:-1]
    elif surname.endswith(("ская", "цкая")):
        gender = "f"
        stem = surname[:-4] + "ск"
    elif surname.endswith(("ая", "яя")) and len(surname) > 4:
        gender = "f"
        stem = surname[:-2]
    elif surname.endswith(("ов", "ев", "ёв", "ин", "ын")):
        gender = "m"
        stem = surname
    elif surname.endswith(("ский", "цкий")):
        gender = "m"
        stem = surname[:-4] + "ск"
    elif surname.endswith(("ый", "ий")) and len(surname) > 4:
        gender = "m"
        stem = surname[:-2]
    else:
        gender = "u"

    return {
        "full_name": full_name,
        "surname": surname,
        "stem": stem,
        "gender": gender,
        "initials": initials
    }


# Извлечение инициалов из запроса студента
def extract_query_initials(query_text: str) -> list[str]:
    # Шаблон с точками: "В.В.", "В. В.", "В."
    dot_inits = re.findall(r"\b([а-яёa-z])\.(?:\s*([а-яёa-z])\.)?", query_text, flags=re.IGNORECASE)
    inits = []
    for m in dot_inits:
        for char in m:
            if char:
                inits.append(char.lower())
    if inits:
        return inits

    # Шаблон раздельных заглавных букв: "Храмцов В В"
    space_inits = re.findall(r"(?<=\s)([А-ЯЁA-Z])(?:\s+([А-ЯЁA-Z]))?(?=\s|$)", query_text)
    for m in space_inits:
        for char in m:
            if char and char.lower() not in {"в", "с", "к", "у", "о", "и"}:
                inits.append(char.lower())
    return inits


def analyze_query_word(word: str) -> tuple[str, str | None]:
    w = word.lower().strip()

    if w.endswith(("овой", "евой", "ёвой", "иной", "ыной")):
        base = w[:-4] + ("ов" if w.endswith("овой") else ("ев" if w.endswith("евой") else "ин"))
        return base, "f"
    if w.endswith(("ской", "цкой", "скую", "цкую", "ская", "цкая")):
        return w[:-4] + "ск", "f"
    if w.endswith(("ая", "яя", "ую", "юю")) and len(w) > 4:
        return w[:-2], "f"

    if w.endswith(("овым", "евым", "ёвым", "иным", "ыным")):
        base = w[:-4] + ("ов" if w.endswith("овым") else ("ев" if w.endswith("евым") else "ин"))
        return base, "m"
    if w.endswith(("ове", "еве", "ёве", "ине", "ыне")):
        base = w[:-3] + ("ов" if w.endswith("ове") else ("ев" if w.endswith("еве") else "ин"))
        return base, "m"
    if w.endswith(("ов", "ев", "ёв", "ин", "ын")):
        return w, "m"
    if any(w.endswith(end) for end in ("ского", "цкого", "скому", "цкому", "ским", "цким", "ском", "цком")):
        return w[:-5] + "ск" if len(w) > 5 else w, "m"
    if w.endswith(("ский", "цкий")):
        return w[:-4] + "ск", "m"
    if any(w.endswith(end) for end in ("ого", "его", "ому", "ему")):
        return w[:-3], "m"
    if any(w.endswith(end) for end in ("ый", "ий", "ым", "им", "ом", "ем")) and len(w) > 4:
        return w[:-2], "m"

    if w.endswith(("ова", "ева", "ёва", "ина", "ына")):
        base = w[:-3] + ("ов" if w.endswith("ова") else ("ев" if w.endswith("ева") else "ин"))
        return base, "ambiguous_a"

    if w.endswith(("ову", "еву", "ёву", "ину", "ыну")):
        base = w[:-3] + ("ов" if w.endswith("ову") else ("ев" if w.endswith("еву") else "ин"))
        return base, "ambiguous_u"

    if len(w) >= 4:
        if w.endswith(("а", "я")):
            return w[:-1], "ambiguous_consonant_a"
        if w.endswith(("у", "ю")):
            return w[:-1], "m"

    return w, None


# Система скоринга совпадений
def score_teacher_match(
    query_text: str,
    query_word: str,
    query_inits: list[str],
    teacher_prof: dict[str, Any]
) -> int:
    q_stem, q_gender = analyze_query_word(query_word)
    t_stem = teacher_prof["stem"]
    t_gender = teacher_prof["gender"]
    t_inits = teacher_prof["initials"]

    # Проверка основы фамилии
    is_stem_match = (q_stem == t_stem) or (
        len(q_stem) >= 4 and len(t_stem) >= 4 and (
            q_stem.startswith(t_stem[:4]) or t_stem.startswith(q_stem[:4])
        ) and abs(len(q_stem) - len(t_stem)) <= 2
    )

    if not is_stem_match:
        return 0

    score = 50

    # Проверка инициалов (наивысший приоритет при наличии)
    if query_inits:
        if t_inits:
            if query_inits == t_inits:
                score += 150  # Полное совпадение обоих инициалов
            elif len(query_inits) == 1 and query_inits[0] == t_inits[0]:
                score += 80   # Совпадение по первой букве имени
            else:
                score -= 150  # Инициалы чужие — отсекаем
        else:
            score -= 30

    # Оценка грамматического рода и падежа
    if q_gender == "m":
        if t_gender == "m":
            score += 50
        elif t_gender == "f":
            score -= 100  # Студент явно спросил мужчину ("Храмцов", "Храмцовым")

    elif q_gender == "f":
        if t_gender == "f":
            score += 50
        elif t_gender == "m":
            score -= 100  # Студент явно спросил женщину ("Храмцовой", "Храмцовская")

    elif q_gender == "ambiguous_a":
        # Форма на "-а" (например, "Храмцова"):
        # Если есть слова "пары", "расписание" — это мужской род в родительном падеже ("пары Храмцова")
        has_genitive_context = any(w in query_text.lower() for w in ["пары", "пара", "расписание", "у", "кого"])
        if has_genitive_context:
            if t_gender == "m":
                score += 40
            elif t_gender == "f":
                score += 15
        else:
            # Одиночный ввод "Храмцова" — именительный падеж женщины
            if t_gender == "f":
                score += 40
            elif t_gender == "m":
                score += 15

    elif q_gender == "ambiguous_u":
        if t_gender == "m":
            score += 30
        elif t_gender == "f":
            score += 20

    elif q_gender == "ambiguous_consonant_a":
        if t_stem == q_stem:
            score += 40
        else:
            score += 10

    return max(0, score)


def _is_valid_classroom_number(room_name: str) -> bool:
    r = room_name.strip().lower()
    if not r or r in ("—", "-", "?", "none", "null", "дистанционно", "zoom", "teams", "онлайн", "спортзал", "бассейн", "стадион"):
        return False
    # Исключаем поточки
    if any(p_num in r and ("п.а" in r or "па" in r or "поточ" in r) for p_num in ["1", "2", "3"]):
        return False
    # Кабинет должен содержать номер (например 102, 226, 301а)
    return bool(re.search(r"\b\d{2,4}[а-яa-z]?\b", r))


class ScheduleCache:
    def __init__(self) -> None:
        self._groups_by_id: dict[int, GroupDTO] = {}
        self._groups_by_course_num: dict[tuple[int, str], GroupDTO] = {}
        self._weeks_by_course: dict[int, list[WeekDTO]] = {}
        self._lessons_by_group_week: dict[tuple[int, int], list[LessonDTO]] = {}
        self._teacher_records: dict[str, list[tuple[LessonDTO, GroupDTO, WeekDTO]]] = {}
        self._teachers_list: list[str] = []
        self._known_rooms: set[str] = set()
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
            "rooms_count": len(self._known_rooms),
        }

    async def reload_from_db(self, session: AsyncSession) -> None:
        logger.info("🧠 [Cache] Загрузка данных из БД в In-Memory кэш...")

        groups_res = await session.execute(select(Group))
        db_groups = groups_res.scalars().all()

        new_groups_by_id: dict[int, GroupDTO] = {}
        new_groups_by_course_num: dict[tuple[int, str], GroupDTO] = {}

        for g in db_groups:
            clean_num = str(g.number).strip()
            dto = GroupDTO(
                id=g.id,
                course=g.course,
                number=clean_num,
                name=g.name,
                study_mode=g.study_mode or "Дневная"
            )
            new_groups_by_id[g.id] = dto
            new_groups_by_course_num[(g.course, clean_num)] = dto

        weeks_res = await session.execute(select(Week).order_by(Week.start_date.desc()))
        db_weeks = weeks_res.scalars().all()

        new_weeks_by_id: dict[int, WeekDTO] = {}
        new_weeks_by_course: dict[int, list[WeekDTO]] = defaultdict(list)

        for w in db_weeks:
            dto = WeekDTO(
                id=w.id,
                course=w.course,
                start_date=w.start_date,
                study_mode=w.study_mode or "Дневная"
            )
            new_weeks_by_id[w.id] = dto
            new_weeks_by_course[w.course].append(dto)

        lessons_res = await session.execute(select(Lesson))
        db_lessons = lessons_res.scalars().all()

        new_lessons_by_group_week: dict[tuple[int, int], list[LessonDTO]] = defaultdict(list)
        new_teacher_records: dict[str, list[tuple[LessonDTO, GroupDTO, WeekDTO]]] = defaultdict(list)
        new_teachers_set: set[str] = set()
        new_rooms_set: set[str] = set()

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
                specialization_order=getattr(l, "specialization_order", None),
                common_discipline=getattr(l, "common_discipline", None)
            )
            new_lessons_by_group_week[(l.group_id, l.week_id)].append(lesson_dto)

            if l.room:
                r_clean = l.room.strip()
                if _is_valid_classroom_number(r_clean):
                    new_rooms_set.add(r_clean)

            if l.teacher:
                teacher_clean = l.teacher.strip()
                new_teachers_set.add(teacher_clean)
                group_dto = new_groups_by_id.get(l.group_id)
                week_dto = new_weeks_by_id.get(l.week_id)
                if group_dto and week_dto:
                    new_teacher_records[teacher_clean].append((lesson_dto, group_dto, week_dto))

        self._groups_by_id = new_groups_by_id
        self._groups_by_course_num = new_groups_by_course_num
        self._weeks_by_course = dict(new_weeks_by_course)
        self._lessons_by_group_week = dict(new_lessons_by_group_week)
        self._teacher_records = dict(new_teacher_records)
        self._teachers_list = sorted(list(new_teachers_set))
        self._known_rooms = new_rooms_set
        self._is_ready = True

        logger.info(
            f"✨ [Cache] Кэш готов: {len(self._groups_by_id)} групп (1-5 курс), "
            f"{len(db_lessons)} пар, {len(self._teachers_list)} преподавателей, {len(self._known_rooms)} учебных кабинетов"
        )

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

    def find_teacher_schedule(self, query_text: str, target_date: date) -> tuple[str, date, list[TeacherSlotDTO]] | None:
        clean = re.sub(r"[^\w\s-]", " ", query_text.lower())
        words = [w for w in clean.split() if w not in TEACHER_STOP_WORDS and len(w) >= 3]
        if not words or not self._teachers_list:
            return None

        query_inits = extract_query_initials(query_text)

        # Оценка совпадения каждого преподавателя в базе с запросом студента
        scored_candidates: list[tuple[int, str]] = []
        for t_name in self._teachers_list:
            prof = parse_teacher_profile(t_name)
            max_word_score = 0
            for word in words:
                s = score_teacher_match(query_text, word, query_inits, prof)
                if s > max_word_score:
                    max_word_score = s

            if max_word_score > 40:
                scored_candidates.append((max_word_score, t_name))

        if not scored_candidates:
            return None

        # Сортировка по очкам совпадения
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_teacher = scored_candidates[0]

        # Защита от слияния: берем расписание ТОЛЬКО ОДНОГО лучшего преподавателя
        records = self._teacher_records.get(best_teacher, [])
        if not records:
            return None

        display_name = best_teacher

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
                    groups=[g_tag]
                )
            else:
                if g_tag not in grouped_slots[key].groups:
                    grouped_slots[key].groups.append(g_tag)

        lessons_list: list[TeacherSlotDTO] = []
        for item in grouped_slots.values():
            item.groups.sort()
            item.groups_display = ", ".join(item.groups)
            lessons_list.append(item)

        return display_name, actual_monday, lessons_list

    def find_subject_schedule(
        self,
        target_date: date,
        canon_subject: str,
        schedule_stems: list[str] | None = None,
        raw_word: str = "",
        query_course: int | None = None,
        query_group_num: str | None = None,
    ) -> tuple[str, date, list[SubjectSlotDTO], str | None] | None:
        stems = [s.lower() for s in (schedule_stems or [canon_subject, raw_word]) if len(s) >= 3]

        def is_match(subj: str) -> bool:
            subj_l = subj.lower()
            return any(stem in subj_l for stem in stems)

        monday = target_date - timedelta(days=target_date.weekday())
        all_courses = sorted(list(self._weeks_by_course.keys()))

        def collect_for_courses(courses: list[int]) -> tuple[date, list[tuple[LessonDTO, GroupDTO, WeekDTO]]]:
            matched: list[tuple[LessonDTO, GroupDTO, WeekDTO]] = []
            act_m = monday
            for c in courses:
                weeks = self._weeks_by_course.get(c, [])
                target_w = next((w for w in weeks if w.start_date == monday), None)
                if not target_w and weeks:
                    target_w = weeks[0]
                if not target_w:
                    continue
                act_m = target_w.start_date

                for g in self.get_all_groups_for_course(c):
                    if query_group_num and str(g.number).strip() != str(query_group_num).strip():
                        continue

                    lessons = self._lessons_by_group_week.get((g.id, target_w.id), [])
                    for l in lessons:
                        if is_match(l.subject):
                            matched.append((l, g, target_w))
            return act_m, matched

        # 1. Сначала ищем по целевому курсу
        if query_course and query_course in self._weeks_by_course:
            actual_monday, records = collect_for_courses([query_course])
        else:
            actual_monday, records = collect_for_courses(all_courses)

        # 2. Если на целевом курсе не найдено и группа не была жестко ограничена — ищем по остальным
        if not records and query_course and not query_group_num:
            actual_monday, records = collect_for_courses(all_courses)

        if not records:
            return None

        # Красивое название: берём самое частотное оригинальное имя из базы
        subject_names = [r[0].subject for r in records]
        display_title = Counter(subject_names).most_common(1)[0][0] if subject_names else canon_subject

        # Честное (возможно) формирование плашки курса/группы на основе РЕАЛЬНО найденных данных
        found_courses = sorted(list({r[1].course for r in records}))
        if query_group_num:
            badge = f"👥 Группа {query_course}-{query_group_num}" if query_course else f"👥 Группа {query_group_num}"
        elif len(found_courses) == 1:
            badge = f"🎓 {found_courses[0]} курс"
        elif len(found_courses) > 1:
            badge = f"🎓 {', '.join(str(c) for c in found_courses)} курсы"
        else:
            badge = None

        grouped_slots: dict[tuple, SubjectSlotDTO] = {}
        for lesson, group, week in records:
            g_tag = f"{group.course}-{group.number}" if group else "?"
            key = (lesson.day, lesson.slot_id, lesson.teacher, lesson.lesson_type, lesson.room, lesson.subgroup)

            if key not in grouped_slots:
                grouped_slots[key] = SubjectSlotDTO(
                    day=lesson.day,
                    slot_id=lesson.slot_id,
                    teacher=lesson.teacher,
                    lesson_type=lesson.lesson_type,
                    room=lesson.room,
                    address=lesson.address,
                    subgroup=lesson.subgroup,
                    groups=[g_tag],
                    subject_name=lesson.subject
                )
            else:
                if g_tag not in grouped_slots[key].groups:
                    grouped_slots[key].groups.append(g_tag)

        lessons_list: list[SubjectSlotDTO] = list(grouped_slots.values())
        for item in lessons_list:
            item.groups.sort()
            item.groups_display = ", ".join(item.groups)

        lessons_list.sort(key=lambda x: (x.day, x.slot_id))
        return display_title, actual_monday, lessons_list, badge

    # Поиск расписания конкретной аудитории / поточки
    def find_room_schedule(self, room_query: str, target_date: date) -> tuple[str, date, list[RoomSlotDTO]] | None:
        clean_q = room_query.lower().strip()
        monday = target_date - timedelta(days=target_date.weekday())

        def is_room_match(raw_room: str | None) -> bool:
            if not raw_room:
                return False
            r = raw_room.strip().lower()

            # Проверка поточек 1-3
            if "п.а." in clean_q or "поточ" in clean_q or "па" in clean_q:
                pot_num = clean_q[0]
                if r == pot_num or bool(re.search(rf"\b{pot_num}\s*(?:п\.?а\.?|па|поточн[а-я]*|поточк[а-я]*)\b", r)):
                    return True
                return False

            # Проверка точного номера кабинета
            return bool(re.search(rf"\b{re.escape(clean_q)}\b", r)) or clean_q in r

        all_matches: list[tuple[LessonDTO, GroupDTO]] = []
        for course, weeks in self._weeks_by_course.items():
            target_w = next((w for w in weeks if w.start_date == monday), None)
            if not target_w and weeks:
                target_w = weeks[0]
            if not target_w:
                continue

            for g in self.get_all_groups_for_course(course):
                lessons = self._lessons_by_group_week.get((g.id, target_w.id), [])
                for l in lessons:
                    if is_room_match(l.room):
                        all_matches.append((l, g))

        if not all_matches:
            return None

        matched_room_names = [l[0].room for l in all_matches if l[0].room]
        display_room = Counter(matched_room_names).most_common(1)[0][0] if matched_room_names else room_query

        grouped: dict[tuple, RoomSlotDTO] = {}
        for lesson, group in all_matches:
            g_tag = f"{group.course}-{group.number}" if group else "?"
            key = (lesson.day, lesson.slot_id, lesson.subject, lesson.teacher, lesson.lesson_type)

            if key not in grouped:
                grouped[key] = RoomSlotDTO(
                    day=lesson.day,
                    slot_id=lesson.slot_id,
                    subject=lesson.subject,
                    lesson_type=lesson.lesson_type,
                    room=display_room,
                    address=lesson.address,
                    teacher=lesson.teacher,
                    subgroup=lesson.subgroup,
                    groups=[g_tag]
                )
            else:
                if g_tag not in grouped[key].groups:
                    grouped[key].groups.append(g_tag)

        slots_list = list(grouped.values())
        for s in slots_list:
            s.groups.sort()
            s.groups_display = ", ".join(s.groups)

        slots_list.sort(key=lambda x: (x.day, x.slot_id))
        return display_room, monday, slots_list

    # Поиск свободных аудиторий на конкретную пару
    def find_free_rooms(
        self,
        target_date: date,
        day_index: int,
        slot_id: int | None = None,
        only_potochki: bool = False
    ) -> tuple[list[str], list[str]]:
        monday = target_date - timedelta(days=target_date.weekday())
        occupied_rooms: set[str] = set()

        for course, weeks in self._weeks_by_course.items():
            target_w = next((w for w in weeks if w.start_date == monday), None)
            if not target_w and weeks:
                target_w = weeks[0]
            if not target_w:
                continue

            for g in self.get_all_groups_for_course(course):
                lessons = self._lessons_by_group_week.get((g.id, target_w.id), [])
                for l in lessons:
                    if l.day == day_index:
                        if slot_id is None or l.slot_id == slot_id:
                            if l.room:
                                occupied_rooms.add(l.room.strip().lower())

        free_potochki = []
        for p in KNOWN_POTOCHKI:
            p_num = p[0]
            is_busy = any(
                p_num in occ and ("п.а" in occ or "па" in occ or "поточ" in occ or occ == p_num)
                for occ in occupied_rooms
            )
            if not is_busy:
                free_potochki.append(p)

        if only_potochki:
            return free_potochki, []

        free_classrooms = []
        for r in sorted(list(self._known_rooms)):
            r_lower = r.lower().strip()
            if r_lower not in occupied_rooms:
                free_classrooms.append(r)

        return free_potochki, free_classrooms

    # Поиск свободных аудиторий на весь день целиком
    def find_free_rooms_whole_day(
        self,
        target_date: date,
        day_index: int,
        only_potochki: bool = False
    ) -> dict[str, Any]:
        monday = target_date - timedelta(days=target_date.weekday())

        slots_occupied: dict[int, set[str]] = defaultdict(set)
        all_day_occupied: set[str] = set()

        for course, weeks in self._weeks_by_course.items():
            target_w = next((w for w in weeks if w.start_date == monday), None)
            if not target_w and weeks:
                target_w = weeks[0]
            if not target_w:
                continue

            for g in self.get_all_groups_for_course(course):
                lessons = self._lessons_by_group_week.get((g.id, target_w.id), [])
                for l in lessons:
                    if l.day == day_index and l.room:
                        r_clean = l.room.strip().lower()
                        slots_occupied[l.slot_id].add(r_clean)
                        all_day_occupied.add(r_clean)

        slots_summary = []
        for slot_id in range(1, 7):
            occupied_now = slots_occupied.get(slot_id, set())

            free_pot = []
            for p in KNOWN_POTOCHKI:
                p_num = p[0]
                is_busy = any(
                    p_num in occ and ("п.а" in occ or "па" in occ or "поточ" in occ or occ == p_num)
                    for occ in occupied_now
                )
                if not is_busy:
                    free_pot.append(p)

            free_cls = []
            if not only_potochki:
                for r in sorted(list(self._known_rooms)):
                    r_lower = r.lower().strip()
                    if r_lower not in occupied_now:
                        free_cls.append(r)

            slots_summary.append({
                "slot_id": slot_id,
                "free_potochki": free_pot,
                "free_classrooms_count": len(free_cls),
                "free_classrooms_preview": free_cls[:8]
            })

        all_day_free_classrooms = []
        if not only_potochki:
            for r in sorted(list(self._known_rooms)):
                r_lower = r.lower().strip()
                if r_lower not in all_day_occupied:
                    all_day_free_classrooms.append(r)

        return {
            "target_date": target_date,
            "day_index": day_index,
            "slots_summary": slots_summary,
            "all_day_free": all_day_free_classrooms
        }

    def get_specializations_for_group(self, group_id: int, course: int) -> dict[int, str]:
        specs: dict[int, str] = {}
        weeks = self._weeks_by_course.get(course, [])
        for w in weeks:
            lessons = self._lessons_by_group_week.get((group_id, w.id), [])
            for l in lessons:
                if l.specialization_order is not None:
                    subj = re.sub(r"\[.*?\]", "", l.subject).strip()
                    specs[l.specialization_order] = subj

        return dict(sorted(specs.items(), key=lambda x: x[0]))

    def get_teacher_index(self, teacher_name: str) -> int:
        try:
            return self._teachers_list.index(teacher_name)
        except ValueError:
            return -1

    def get_teacher_by_index(self, idx: int) -> str | None:
        if 0 <= idx < len(self._teachers_list):
            return self._teachers_list[idx]
        return None

    def find_group_by_number_any_course(self, number: str | int) -> GroupDTO | None:
        clean_num = str(number).strip()
        for (course, num), group in self._groups_by_course_num.items():
            if num == clean_num or clean_num.endswith(f"-{num}") or num.endswith(f"-{clean_num}"):
                return group
        return None


schedule_cache = ScheduleCache()