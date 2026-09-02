import re
from datetime import timedelta
from typing import Any
from config import get_minsk_now
from services.subject_dict import extract_subject_from_query

DAY_TARGETS_MAP = {
    # Понедельник
    "пн": 0, "пон": 0, "понедельник": 0, "понедельнику": 0, "понедельника": 0, "понедельнике": 0, "понедельнек": 0,
    # Вторник
    "вт": 1, "втор": 1, "вторник": 1, "вторнику": 1, "вторника": 1, "вторнике": 1, "вторнек": 1,
    # Среда
    "ср": 2, "сред": 2, "среда": 2, "среду": 2, "среды": 2, "среде": 2,
    # Четверг
    "чт": 3, "чет": 3, "четверг": 3, "четвергу": 3, "четверга": 3, "четверге": 3, "четверк": 3,
    # Пятница
    "пт": 4, "пят": 4, "пятница": 4, "пятницу": 4, "пятницы": 4, "пятнице": 4, "пятнеца": 4,
    # Суббота
    "сб": 5, "суб": 5, "суббота": 5, "субботу": 5, "субботы": 5, "субботе": 5, "субота": 5,
    # Воскресенье
    "вс": 6, "вск": 6, "воскресенье": 6, "воскресенью": 6, "воскресенья": 6, "воскресение": 6,
    # Относительные дни
    "сегодня": "today", "седня": "today", "севодня": "today", "сгодня": "today",
    "завтра": "tomorrow", "завтро": "tomorrow",
    "послезавтра": "after_tomorrow", "послезавтро": "after_tomorrow",
    "сейчас": "current", "щас": "current", "щяс": "current", "ща": "current",
}

PAIR_TARGETS = {
    "первая": 1, "первой": 1, "первую": 1, "1-я": 1, "1-ая": 1, "1ая": 1, "1я": 1, "1ую": 1, "1-ую": 1,
    "вторая": 2, "второй": 2, "вторую": 2, "2-я": 2, "2-ая": 2, "2ая": 2, "2я": 2, "2ую": 2, "2-ую": 2,
    "третья": 3, "третьей": 3, "третью": 3, "3-я": 3, "3-ья": 3, "3ья": 3, "3я": 3, "3ью": 3, "3-ью": 3,
    "четвертая": 4, "четвертой": 4, "четвёртая": 4, "четвертую": 4, "четвёртую": 4, "4-я": 4, "4-ая": 4, "4ая": 4, "4я": 4, "4ую": 4, "4-ую": 4,
    "пятая": 5, "пятой": 5, "пятую": 5, "5-я": 5, "5-ая": 5, "5ая": 5, "5я": 5, "5ую": 5, "5-ую": 5,
    "шестая": 6, "шестой": 6, "шестую": 6, "6-я": 6, "6-ая": 6, "6ая": 6, "6я": 6, "6ую": 6, "6-ую": 6,
    "седьмая": 7, "седьмой": 7, "седьмую": 7, "7-я": 7, "7-ая": 7, "7ая": 7, "7я": 7, "7ую": 7, "7-ую": 7,
    "восьмая": 8, "восьмой": 8, "восьмую": 8, "8-я": 8, "8-ая": 8, "8ая": 8, "8я": 8, "8ую": 8, "8-ую": 8,
}

POTOCHKA_WORDS_MAP = {
    "1": "1", "перв": "1", "1-я": "1", "1-ой": "1", "1-ую": "1", "1я": "1",
    "2": "2", "втор": "2", "2-я": "2", "2-ой": "2", "2-ую": "2", "2я": "2",
    "3": "3", "трет": "3", "3-я": "3", "3-ей": "3", "3-ью": "3", "3я": "3",
}

# Регулярка для поточек (только 1, 2, 3)
POTOCHKA_REGEX = re.compile(
    r"\b([1-3]|перв[а-я]*|втор[а-я]*|трет[а-я]*)\s*(?:-(?:я|ая|ей|ой|ую|ем|ом|й|ья|ью))?\s*(?:п[оа]точк[а-я]*|п[оа]точн[а-я]*|п\.?а\.?|п/а)\b"
    r"|\b(?:п[оа]точк[а-я]*|п[оа]точн[а-я]*|п\.?а\.?|п/а)\s*([1-3]|перв[а-я]*|втор[а-я]*|трет[а-я]*)\b",
    re.IGNORECASE
)

# Регулярка для номеров учебных кабинетов (208, ауд 331, каб 104)
ROOM_NUMBER_REGEX = re.compile(
    r"(?:\b(?:ауд(?:итори[ияею])?|каб(?:инет[а-я]*)?|комнат[а-я]*)\s*([0-9]{2,4}[а-яА-Яa-zA-Z]?)\b)"
    r"|(?:\b(?:в|во)\s+([0-9]{2,4}[а-яА-Яa-zA-Z]?)\b)"
    r"|(?:\b([0-9]{3,4}[а-яА-Яa-zA-Z]?)\s*(?:ауд|каб)?\b)"
)

# Регулярка для пар
PAIR_REGEX = re.compile(
    r"\b([1-8])\s*(?:-(?:я|ая|ей|ую|е|й|ья|ью)|(?:я|ая|ей|ую|е|й|ья|ью))?\s*(?:пара|пары|паре|пару|парой)\b"
    r"|\b([1-8])-(?:я|ая|ей|ую|е|й|ья|ью)\s+(?:пара|пары|паре|пару|парой)\b"
    r"|\b([1-8])\s*пара\b"
)

# Поиск группы вида 1-41, 2-42
GROUP_REGEX = re.compile(
    r"\b([1-5])\s*[-_/\\]\s*([0-9]+(?:-[0-9]+)*)(?!\s*-(?:я|ая|ей|ую|е|й))\b"
)

COURSE_REGEX = re.compile(
    r"\b([1-5])\s*(?:-?(?:ый|ой|ий|й|ем|ом|е|у))?\s*курс[а-я]*\b",
    re.IGNORECASE
)

FREE_ROOMS_KEYWORDS = re.compile(
    r"\b(свободн[а-я]*|пуст[а-я]*|где\s+посидеть|где\s+сесть|где\s+свободно)\b",
    re.IGNORECASE
)

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
    r"|шо\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r")\b",
    re.IGNORECASE
)

WEEK_KEYWORDS = {"неделя", "неделю", "неделе", "недели", "нед", "расписание"}


def parse_schedule_query(text: str) -> dict[str, Any] | None:
    today = get_minsk_now().date()
    working_text = text.lower().strip()

    # Очистка вводных служебных слов
    working_text = re.sub(
        r"\b(?:чо|че|шо|что|там|у|по|для|плиз|пожалуйста|скинь|подскажи|покажи|дай|какие|какая|какой|кто|занято|занята)\b",
        " ",
        working_text
    )
    working_text = re.sub(r"\s+", " ", working_text).strip()

    if not working_text:
        return None

    # 1. Извлечение поточки / аудитории
    room_query = None
    room_display = None

    pot_match = POTOCHKA_REGEX.search(working_text)
    if pot_match:
        raw_pot_num = (pot_match.group(1) or pot_match.group(2)).lower()
        pot_num = "1"
        for k, v in POTOCHKA_WORDS_MAP.items():
            if raw_pot_num.startswith(k):
                pot_num = v
                break
        room_query = f"{pot_num} п.а."
        room_display = f"{pot_num}-я поточная аудитория"
        # Вырезаем поточку, чтобы она не мешала поиску пары
        working_text = working_text[:pot_match.start()] + " " + working_text[pot_match.end():]
        working_text = re.sub(r"\s+", " ", working_text).strip()

    elif not GROUP_REGEX.search(working_text):
        room_match = ROOM_NUMBER_REGEX.search(working_text)
        if room_match:
            room_num = (room_match.group(1) or room_match.group(2) or room_match.group(3)).strip()
            if room_num and (len(room_num) >= 2 or int(room_num) > 8):
                room_query = room_num
                room_display = f"Аудитория {room_num}"
                # Вырезаем номер кабинета
                working_text = working_text[:room_match.start()] + " " + working_text[room_match.end():]
                working_text = re.sub(r"\s+", " ", working_text).strip()

    # 2. Поиск группы (1-41, 2-42)
    target_group = None
    group_match = GROUP_REGEX.search(working_text)
    if group_match:
        course = int(group_match.group(1))
        group_num = group_match.group(2).strip()
        target_group = {"course": course, "group_number": group_num}
        working_text = working_text[:group_match.start()] + " " + working_text[group_match.end():]
        working_text = re.sub(r"\s+", " ", working_text).strip()

    # 3. Поиск курса (2 курс)
    target_course = None
    course_match = COURSE_REGEX.search(working_text)
    if course_match:
        target_course = int(course_match.group(1))
        working_text = working_text[:course_match.start()] + " " + course_match[course_match.end():]
        working_text = re.sub(r"\s+", " ", working_text).strip()

    # 4. Поиск дисциплины (ботаника, микра и тд.)
    subj_match = extract_subject_from_query(text)
    if subj_match and not room_query and not FREE_ROOMS_KEYWORDS.search(text):
        canon_name, raw_word = subj_match
        return {
            "type": "subject",
            "canon_subject": canon_name,
            "raw_subject_word": raw_word,
            "date": today,
            "target_group": target_group,
            "target_course": target_course or (target_group["course"] if target_group else None),
        }

    # 5. Поиск пары (1 пара, 3 парой и тд.)
    matched_slot_id = None
    pair_match = PAIR_REGEX.search(working_text)
    if pair_match:
        matched_slot_id = int(pair_match.group(1) or pair_match.group(2) or pair_match.group(3))
        working_text = working_text[:pair_match.start()] + " " + pair_match[pair_match.end():]
        working_text = re.sub(r"\s+", " ", working_text).strip()

    # 6. Поиск дня недели / даты
    is_next_week = any(w in working_text for w in ["след", "следующ", "будущ", "next"])
    words = working_text.split()

    matched_day_val = None
    for w in words:
        if matched_day_val is None and w in DAY_TARGETS_MAP:
            matched_day_val = DAY_TARGETS_MAP[w]
        if matched_slot_id is None and w in PAIR_TARGETS:
            matched_slot_id = PAIR_TARGETS[w]

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

    # Запрос конкретной поточки / аудитории
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

    # Запрос недели
    has_week_word = any(w in WEEK_KEYWORDS for w in words)
    if has_week_word or (target_group and not working_text):
        monday = today - timedelta(days=today.weekday())
        if is_next_week or (today.weekday() >= 5 and has_week_word):
            monday += timedelta(days=7)
        return {
            "type": "week",
            "date": monday,
            "day_index": 0,
            "target_group": target_group,
        }

    # Текущая локация / пара группы
    is_current_query = bool(CURRENT_LOCATION_REGEX.search(text))

    if target_group and matched_day_val is None and matched_slot_id is None and not is_current_query:
        matched_day_val = "today"

    if matched_day_val is None and matched_slot_id is None and not is_current_query:
        return None

    if matched_day_val == "current" or (is_current_query and matched_day_val is None and matched_slot_id is None):
        return {
            "type": "current",
            "date": today,
            "day_index": day_index,
            "target_group": target_group,
        }

    if matched_slot_id is not None:
        return {
            "type": "slot",
            "slot_id": matched_slot_id,
            "date": target_date,
            "day_index": day_index,
            "target_group": target_group,
        }

    return {
        "type": "day",
        "date": target_date,
        "day_index": day_index,
        "target_group": target_group,
    }