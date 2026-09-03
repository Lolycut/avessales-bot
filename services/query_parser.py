import re
from datetime import timedelta
from typing import Any
from config import get_minsk_now
from services.subject_dict import extract_subject_from_query

DAY_TARGETS_MAP = {
    "пн": 0, "пон": 0, "понедельник": 0, "понедельнику": 0, "понедельника": 0, "понедельнике": 0,
    "вт": 1, "втор": 1, "вторник": 1, "вторнику": 1, "вторника": 1, "вторнике": 1,
    "ср": 2, "сред": 2, "среда": 2, "среду": 2, "среды": 2, "среде": 2,
    "чт": 3, "чет": 3, "четверг": 3, "четвергу": 3, "четверга": 3, "четверге": 3,
    "пт": 4, "пят": 4, "пятница": 4, "пятницу": 4, "пятницы": 4, "пятнице": 4,
    "сб": 5, "суб": 5, "суббота": 5, "субботу": 5, "субботы": 5, "субботе": 5,
    "вс": 6, "вск": 6, "воскресенье": 6, "воскресенью": 6, "воскресенья": 6,
    "сегодня": "today", "седня": "today", "сгодня": "today",
    "завтра": "tomorrow", "завтро": "tomorrow",
    "послезавтра": "after_tomorrow",
    "сейчас": "current", "щас": "current", "ща": "current",
}

PAIR_WORDS_MAP = {
    "перв": 1, "1-": 1, "1": 1,
    "втор": 2, "2-": 2, "2": 2,
    "трет": 3, "3-": 3, "3": 3,
    "четверт": 4, "четвёрт": 4, "4-": 4, "4": 4,
    "пят": 5, "5-": 5, "5": 5,
    "шест": 6, "6-": 6, "6": 6,
    "седьм": 7, "7-": 7, "7": 7,
    "восьм": 8, "8-": 8, "8": 8,
}

# Регулярка пар: "ко 2 паре", "на 3 пару", "со 2 пары", "3 пара", "2-я пара", "пара 2", "3 парой"
COMPREHENSIVE_PAIR_REGEX = re.compile(
    r"(?:\b(?:к|ко|на|со|с|до)?\s*([1-8])\s*(?:-?(?:я|ая|ей|ой|ую|е|й|ья|ью|пара|пары|паре|пару|парой))?\s*(?:пара|пары|паре|пару|парой)\b)"
    r"|(?:\b(?:пара|паре|пару|парой)\s*([1-8])\b)"
    r"|(?:\b([1-8])\s*[-–—]?\s*(?:я|ая|ей|ую|е|й|ья|ью)\s*паро?й?\b)"
    r"|(?:\b(?:к|ко|на|со|с)?\s*(перв[а-я]*|втор[а-я]*|трет[а-я]*|четверт[а-я]*|четвёрт[а-я]*|пят[а-я]*|шест[а-я]*|седьм[а-я]*|восьм[а-я]*)\s*(?:паре|пару|пара|парой)\b)",
    re.IGNORECASE
)

POTOCHKA_REGEX = re.compile(
    r"\b([1-3]|перв[а-я]*|втор[а-я]*|трет[а-я]*)\s*(?:-(?:я|ая|ей|ой|ую|ем|ом|й|ья|ью))?\s*(?:п[оа]точк[а-я]*|п[оа]точн[а-я]*|п\.?а\.?|п/а)\b"
    r"|\b(?:п[оа]точк[а-я]*|п[оа]точн[а-я]*|п\.?а\.?|п/а)\s*([1-3]|перв[а-я]*|втор[а-я]*|трет[а-я]*)\b",
    re.IGNORECASE
)

ROOM_NUMBER_REGEX = re.compile(
    r"(?:\b(?:ауд(?:итори[ияею])?|каб(?:инет[а-я]*)?|комнат[а-я]*)\s*([0-9]{2,4}[а-яА-Яa-zA-Z]?)\b)"
    r"|(?:\b(?:в|во)\s+([0-9]{2,4}[а-яА-Яa-zA-Z]?)\b)"
    r"|(?:\b([0-9]{3,4}[а-яА-Яa-zA-Z]?)\s*(?:ауд|каб)\b)"
)

GROUP_REGEX = re.compile(r"\b([1-5])\s*[-_/\\]\s*([0-9]+(?:-[0-9]+)*)(?!\s*-(?:я|ая|ей|ую|е|й))\b")
COURSE_REGEX = re.compile(r"\b([1-5])\s*(?:-?(?:ый|ой|ий|й|ем|ом|е|у))?\s*курс[а-я]*\b", re.IGNORECASE)
FREE_ROOMS_KEYWORDS = re.compile(r"\b(свободн[а-я]*|пуст[а-я]*|где\s+посидеть|где\s+сесть|где\s+свободно)\b", re.IGNORECASE)

CURRENT_LOCATION_REGEX = re.compile(
    r"\b("
    r"где\s+мы(?:\s+сейчас|\s+щас)?"
    r"|куда\s+(?:идти|нам|ехать)"
    r"|в\s+какой\s+(?:мы\s+)?(?:аудитории|ауде|кабинете|корпусе|ауд)"
    r"|какая\s+(?:у\s+нас\s+)?(?:аудитория|ауда|ауд)"
    r"|какой\s+(?:у\s+нас\s+)?(?:кабинет|корпус)"
    r"|какая\s+(?:сейчас|щас)\s+пара"
    r"|какая\s+пара\s+(?:сейчас|щас)"
    r"|что\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r"|че\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r"|чо\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r")\b",
    re.IGNORECASE
)

WEEK_KEYWORDS = {"неделя", "неделю", "неделе", "недели", "нед", "расписание"}


def parse_schedule_query(text: str) -> dict[str, Any] | None:
    today = get_minsk_now().date()
    working_text = text.lower().strip()

    # 1. Поиск поточной аудитории
    room_query = None
    room_display = None
    pot_match = POTOCHKA_REGEX.search(working_text)
    if pot_match:
        raw_pot = (pot_match.group(1) or pot_match.group(2)).lower()
        pot_num = "1"
        if "2" in raw_pot or "втор" in raw_pot:
            pot_num = "2"
        elif "3" in raw_pot or "трет" in raw_pot:
            pot_num = "3"
        room_query = f"{pot_num} п.а."
        room_display = f"{pot_num}-я поточная аудитория"
        working_text = working_text[:pot_match.start()] + " " + working_text[pot_match.end():]

    # 2. Поиск учебного кабинета (если не поточка)
    elif not GROUP_REGEX.search(working_text):
        room_match = ROOM_NUMBER_REGEX.search(working_text)
        if room_match:
            room_num = (room_match.group(1) or room_match.group(2) or room_match.group(3)).strip()
            if room_num and (len(room_num) >= 2 or int(room_num) > 8):
                room_query = room_num
                room_display = f"Аудитория {room_num}"
                working_text = working_text[:room_match.start()] + " " + working_text[room_match.end():]

    # 3. Поиск группы (1-41, 2-42)
    target_group = None
    group_match = GROUP_REGEX.search(working_text)
    if group_match:
        course = int(group_match.group(1))
        group_num = group_match.group(2).strip()
        target_group = {"course": course, "group_number": group_num}
        working_text = working_text[:group_match.start()] + " " + working_text[group_match.end():]

    # 4. Поиск курса (2 курс)
    target_course = None
    course_match = COURSE_REGEX.search(working_text)
    if course_match:
        target_course = int(course_match.group(1))
        working_text = working_text[:course_match.start()] + " " + course_match[course_match.end():]

    # 5. Поиск предмета (дисциплины)
    subj_match = extract_subject_from_query(text)
    if subj_match and not room_query and not FREE_ROOMS_KEYWORDS.search(text):
        canon_name, stems, raw_word = subj_match
        return {
            "type": "subject",
            "canon_subject": canon_name,
            "schedule_stems": stems,
            "raw_subject_word": raw_word,
            "date": today,
            "target_group": target_group,
            "target_course": target_course or (target_group["course"] if target_group else None),
        }

    # 6. Извлечение номера пары
    matched_slot_id = None
    pair_match = COMPREHENSIVE_PAIR_REGEX.search(working_text)
    if pair_match:
        g1, g2, g3, g4 = pair_match.groups()
        if g1 and g1.isdigit():
            matched_slot_id = int(g1)
        elif g2 and g2.isdigit():
            matched_slot_id = int(g2)
        elif g3 and g3.isdigit():
            matched_slot_id = int(g3)
        elif g4:
            for k, v in PAIR_WORDS_MAP.items():
                if g4.startswith(k):
                    matched_slot_id = v
                    break
        working_text = working_text[:pair_match.start()] + " " + working_text[pair_match.end():]

    # 7. Извлечение дня недели и даты
    is_next_week = any(w in working_text for w in ["след", "следующ", "будущ", "next"])
    words = working_text.split()

    matched_day_val = None
    for w in words:
        if matched_day_val is None and w in DAY_TARGETS_MAP:
            matched_day_val = DAY_TARGETS_MAP[w]
            break

    target_date = today
    day_index = today.weekday()

    if matched_day_val == "tomorrow":
        target_date = today + timedelta(days=1)
        day_index = target_date.weekday()
    elif matched_day_val == "after_tomorrow":
        target_date = today + timedelta(days=2)
        day_index = target_date.weekday()
    elif isinstance(matched_day_val, int):
        days_ahead = (matched_day_val - today.weekday()) % 7
        if is_next_week:
            days_ahead += 7
        target_date = today + timedelta(days=days_ahead)
        day_index = matched_day_val

    # Запрос свободных аудиторий
    if FREE_ROOMS_KEYWORDS.search(text):
        only_potochki = bool(re.search(r"\bпоточк[а-я]*|поточн[а-я]*|п\.?а\.?\b", text, re.IGNORECASE))
        return {
            "type": "free_rooms",
            "date": target_date,
            "day_index": day_index,
            "slot_id": matched_slot_id,
            "only_potochki": only_potochki,
            "is_current": (matched_day_val in ("current", None) and matched_slot_id is None and ("сейчас" in text.lower() or "щас" in text.lower()))
        }

    # Запрос конкретной аудитории / поточки
    if room_query:
        return {
            "type": "room",
            "room_query": room_query,
            "room_display": room_display,
            "date": target_date,
            "day_index": day_index,
            "slot_id": matched_slot_id,
            "is_current": (matched_day_val == "current" or ("сейчас" in text.lower() or "щас" in text.lower()))
        }

    # Неделя
    has_week_word = any(w in WEEK_KEYWORDS for w in words)
    clean_remains = re.sub(r"\b(?:чо|че|шо|что|там|у|по|для|плиз|пожалуйста|скинь|дай)\b", "", working_text).strip()
    if has_week_word or (target_group and not clean_remains and matched_slot_id is None):
        monday = today - timedelta(days=today.weekday())
        if is_next_week or (today.weekday() >= 5 and has_week_word):
            monday += timedelta(days=7)
        return {
            "type": "week",
            "date": monday,
            "day_index": 0,
            "target_group": target_group,
        }

    # Текущая пара / локация
    is_current_query = bool(CURRENT_LOCATION_REGEX.search(text))
    if matched_day_val == "current" or (is_current_query and matched_day_val is None and matched_slot_id is None):
        return {
            "type": "current",
            "date": today,
            "day_index": day_index,
            "target_group": target_group,
        }

    # Слот (конкретная пара)
    if matched_slot_id is not None:
        return {
            "type": "slot",
            "slot_id": matched_slot_id,
            "date": target_date,
            "day_index": day_index,
            "target_group": target_group,
        }

    # Дневной запрос
    if matched_day_val is not None or (target_group and not clean_remains):
        return {
            "type": "day",
            "date": target_date,
            "day_index": day_index,
            "target_group": target_group,
        }

    return None