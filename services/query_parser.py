import re
import difflib
from datetime import timedelta
from typing import Optional, Any, Dict
from config import get_minsk_now

FULL_DAY_TARGETS = {
    "понедельник": 0, "понедельнику": 0, "понедельника": 0, "понедельнике": 0,
    "вторник": 1, "вторнику": 1, "вторника": 1, "вторнике": 1,
    "среда": 2, "среду": 2, "среды": 2, "среде": 2,
    "четверг": 3, "четвергу": 3, "четверга": 3, "четверге": 3,
    "пятница": 4, "пятницу": 4, "пятницы": 4, "пятнице": 4,
    "суббота": 5, "субботу": 5, "субботы": 5, "субботе": 5,
    "воскресенье": 6, "воскресенью": 6, "воскресенья": 6,
    "сегодня": "today", "сейчас": "current",
    "завтра": "tomorrow", "завтро": "tomorrow",
    "послезавтра": "after_tomorrow"
}

SHORT_DAY_TARGETS = {
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6
}

PAIR_TARGETS = {
    "первая": 1, "первой": 1, "первую": 1, "1": 1, "1-я": 1, "1-ой": 1, "1ая": 1, "1ую": 1,
    "вторая": 2, "второй": 2, "вторую": 2, "2": 2, "2-я": 2, "2-ой": 2, "2ая": 2, "2ую": 2,
    "третья": 3, "третьей": 3, "третью": 3, "3": 3, "3-я": 3, "3-ей": 3, "3ья": 3, "3ью": 3,
    "четвертая": 4, "четвертой": 4, "четвёртая": 4, "четвертую": 4, "четвёртую": 4, "4": 4, "4-я": 4, "4ую": 4,
    "пятая": 5, "пятой": 5, "пятую": 5, "5": 5, "5-я": 5, "5ую": 5,
    "шестая": 6, "шестой": 6, "шестую": 6, "6": 6, "6-я": 6, "6ую": 6,
    "седьмая": 7, "седьмой": 7, "седьмую": 7, "7": 7, "7-я": 7, "7ую": 7,
    "восьмая": 8, "восьмой": 8, "восьмую": 8, "8": 8, "8-я": 8, "8ую": 8
}

STOP_WORDS = {"что", "где", "как", "когда", "какая", "какие", "какой", "пары", "пара", "пару", "в", "во", "на", "у"}


def find_day_in_word(word: str) -> Optional[Any]:
    if not word or word in STOP_WORDS:
        return None
    if word in SHORT_DAY_TARGETS:
        return SHORT_DAY_TARGETS[word]
    if word in FULL_DAY_TARGETS:
        return FULL_DAY_TARGETS[word]
    if len(word) >= 4:
        matches = difflib.get_close_matches(word, FULL_DAY_TARGETS.keys(), n=1, cutoff=0.75)
        if matches:
            return FULL_DAY_TARGETS[matches[0]]
    return None


def get_best_fuzzy_match(word: str, dictionary: dict, threshold: float = 0.75):
    if not word or len(word) < 2 or word in STOP_WORDS:
        return None
    if word in dictionary:
        return dictionary[word]
    matches = difflib.get_close_matches(word, dictionary.keys(), n=1, cutoff=threshold)
    if matches:
        return dictionary[matches[0]]
    return None


def parse_schedule_query(text: str) -> Dict[str, Any]:
    today = get_minsk_now().date()
    clean_text = text.lower()

    # 1. Поиск целевой чужой группы (формат: 1-41, 2-2, 3-1, 1-0521-01 и т.д.)
    target_group = None
    group_match = re.search(r"\b([1-4])[-_/\s]([0-9]+(?:-[0-9]+)*)\b", clean_text)
    if group_match:
        course = int(group_match.group(1))
        group_num = group_match.group(2)
        target_group = {"course": course, "group_number": group_num}
        # Удаляем найденную группу из строки, чтобы её цифры не считались номерами пар
        clean_text = clean_text[:group_match.start()] + " " + clean_text[group_match.end():]

    clean_text = re.sub(r"[^\w\s-]", " ", clean_text)
    words = clean_text.split()

    is_next_week = any(w in clean_text for w in ["след", "следующ", "будущ", "next"])
    is_week_query = any(w in clean_text for w in ["неделю", "неделя", "неделе"])

    if is_week_query:
        monday = today - timedelta(days=today.weekday())
        if is_next_week or today.weekday() >= 4:
            monday += timedelta(days=7)
        return {
            "type": "week",
            "date": monday,
            "day_index": 0,
            "target_group": target_group
        }

    matched_day_val = None
    matched_slot_id = None

    digit_match = re.search(r"\b([1-8])\s*(?:-?[яеийуюа-я]*)?\s*(?:пара|парой|пары|пару)?\b", clean_text)
    if digit_match:
        matched_slot_id = int(digit_match.group(1))

    for w in words:
        if matched_day_val is None:
            day_res = find_day_in_word(w)
            if day_res is not None:
                matched_day_val = day_res

        if matched_slot_id is None:
            slot_res = get_best_fuzzy_match(w, PAIR_TARGETS)
            if slot_res is not None:
                matched_slot_id = slot_res

    target_date = today
    day_index = today.weekday()

    if matched_day_val == "current":
        return {"type": "current", "date": today, "day_index": day_index, "target_group": target_group}
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
            "target_group": target_group
        }

    return {
        "type": "day",
        "date": target_date,
        "day_index": day_index,
        "target_group": target_group
    }