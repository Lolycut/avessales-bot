import re
from datetime import timedelta
from typing import Any
from config import get_minsk_now

DAY_TARGETS_MAP = {
    "пн": 0, "пон": 0, "понедельник": 0, "понедельнику": 0, "понедельника": 0, "понедельнике": 0, "понедельнек": 0,
    "вт": 1, "втор": 1, "вторник": 1, "вторнику": 1, "вторника": 1, "вторнике": 1, "вторнек": 1,
    "ср": 2, "сред": 2, "среда": 2, "среду": 2, "среды": 2, "среде": 2,
    "чт": 3, "чет": 3, "четверг": 3, "четвергу": 3, "четверга": 3, "четверге": 3, "четверк": 3,
    "пт": 4, "пят": 4, "пятница": 4, "пятницу": 4, "пятницы": 4, "пятнице": 4, "пятнеца": 4,
    "сб": 5, "суб": 5, "суббота": 5, "субботу": 5, "субботы": 5, "субботе": 5, "субота": 5,
    "вс": 6, "вск": 6, "воскресенье": 6, "воскресенью": 6, "воскресенья": 6, "воскресение": 6,
    "сегодня": "today", "седня": "today", "севодня": "today",
    "сейчас": "current", "щас": "current", "щяс": "current", "ща": "current", "сейчасная": "current",
    "завтра": "tomorrow", "завтро": "tomorrow",
    "послезавтра": "after_tomorrow",
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

GENERAL_SCHEDULE_KEYWORDS = {
    "расписание", "расписанию", "расписанием", "расписании", 
    "пары", "пара", "пару", "парам", "парами", "парах",
    "занятия", "занятий", "уроки", "уроков"
}

# Регулярка для поиска фраз о текущей аудитории / местоположении
CURRENT_LOCATION_REGEX = re.compile(
    r"\b("
    r"где\s+мы(?:\s+сейчас|\s+щас)?"
    r"|куда\s+(?:идти|нам|ехать)"
    r"|в\s+какой\s+(?:мы\s+)?(?:аудитории|ауде|кабинете|корпусе|ауд)"
    r"|какая\s+(?:у\s+нас\s+)?(?:аудитория|ауда|ауд)"
    r"|какой\s+(?:у\s+нас\s+)?(?:кабинет|корпус)"
    r"|где\s+(?:щас|сейчас|пара|пары|занятие)"
    r"|какая\s+(?:сейчас|щас)\s+пара"
    r"|какая\s+пара\s+(?:сейчас|щас)"
    r"|что\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r"|че\s+(?:у\s+нас\s+)?(?:сейчас|щас)"
    r")\b",
    re.IGNORECASE
)

PAIR_REGEX = re.compile(
    r"\b([1-8])\s*(?:-(?:я|ая|ей|ую|е|й|ья|ью)|(?:я|ая|ей|ую|е|й|ья|ью))?\s+(?:пара|пары|паре|пару|парой)\b"
    r"|\b([1-8])-(?:я|ая|ей|ую|е|й|ья|ью)\b"
    r"|\b([1-8])(?:ая|яя|ья|ую|юю|ью)\b"
)

GROUP_REGEX = re.compile(
    r"\b([1-4])\s*[-_/\\]\s*([0-9]+(?:-[0-9]+)*)(?!\s*-(?:я|ая|ей|ую|е|й))(?!\s*(?:пара|пары|паре|пару|парой))\b"
)


def parse_schedule_query(text: str) -> dict[str, Any] | None:
    today = get_minsk_now().date()
    clean_text = text.lower().strip()

    # 1. Поиск чужой группы (1-41, 2-42)
    target_group = None
    group_match = GROUP_REGEX.search(clean_text)
    if group_match:
        course = int(group_match.group(1))
        group_num = group_match.group(2).strip()
        target_group = {"course": course, "group_number": group_num}
        clean_text = clean_text[:group_match.start()] + " " + clean_text[group_match.end():]

    # 2. Недельный запрос
    is_next_week = any(w in clean_text for w in ["след", "следующ", "будущ", "next"])
    is_week_query = any(w in clean_text for w in ["неделю", "неделя", "неделе", "недели"])

    if is_week_query:
        monday = today - timedelta(days=today.weekday())
        if is_next_week or today.weekday() >= 5:
            monday += timedelta(days=7)
        return {
            "type": "week",
            "date": monday,
            "day_index": 0,
            "target_group": target_group,
        }

    # 3. Проверка на запрос текущей пары / локации / аудитории через фразы
    is_current_location_query = bool(CURRENT_LOCATION_REGEX.search(clean_text))

    # 4. Поиск номера пары
    matched_slot_id = None
    pair_match = PAIR_REGEX.search(clean_text)
    if pair_match:
        matched_slot_id = int(pair_match.group(1) or pair_match.group(2) or pair_match.group(3))

    normalized_text = re.sub(r"[^\w\s-]", " ", clean_text)
    words = normalized_text.split()

    matched_day_val = None
    has_general_trigger = False

    for w in words:
        if matched_day_val is None and w in DAY_TARGETS_MAP:
            matched_day_val = DAY_TARGETS_MAP[w]
        if matched_slot_id is None and w in PAIR_TARGETS:
            matched_slot_id = PAIR_TARGETS[w]
        if w in GENERAL_SCHEDULE_KEYWORDS:
            has_general_trigger = True

    # 5. Если сработал вопрос «где мы? / какая аудитория?» без указания другого дня или слота
    if is_current_location_query and matched_day_val is None and matched_slot_id is None:
        return {
            "type": "current",
            "date": today,
            "day_index": today.weekday(),
            "target_group": target_group,
        }

    # 6. Если в сообщении нет явного намерения узнать расписание — игнорируем
    if (
        matched_day_val is None 
        and matched_slot_id is None 
        and target_group is None 
        and not has_general_trigger
        and not is_current_location_query
    ):
        return None

    target_date = today
    day_index = today.weekday()

    if matched_day_val == "current" or (is_current_location_query and matched_day_val is None and matched_slot_id is None):
        return {
            "type": "current",
            "date": today,
            "day_index": day_index,
            "target_group": target_group,
        }
    elif matched_day_val == "today":
        target_date = today
        day_index = today.weekday()
    elif matched_day_val == "tomorrow":
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