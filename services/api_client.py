import asyncio
import httpx
from datetime import date, timedelta
from typing import Any
from collections import defaultdict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_BASE_URL, logger, get_minsk_now
from models import Group, Week, Lesson
from services.dto import ScheduleChangeDTO
from services.notifications import dispatch_schedule_changes

LESSON_TYPES_MAP = {
    "lecture": "ЛК",
    "practice": "ПЗ",
    "lab": "ЛР",
    "seminar": "СМ",
    "other": "ДР"
}

LAST_SYNC_INFO: dict[str, Any] = {
    "timestamp": None,
    "success": True,
    "errors": [],
    "total_lessons_saved": 0,
    "changes_count": 0,
    "changed_groups": []
}


def get_current_date() -> date:
    return get_minsk_now().date()


def short_name(full_name: str | None) -> str:
    if not full_name:
        return "—"
    parts = full_name.strip().split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
    elif len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return full_name


class BioBSUApiClient:
    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.base_url}/schedule/",
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(15.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _safe_get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response | None:
        client = await self.get_client()
        try:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return None
            return response
        except Exception as e:
            logger.error(f"Ошибка запроса к {url}: {e}")
            return None

    async def fetch_groups(self, course: int = 2, study_mode: str = "Дневная") -> list[dict[str, Any]]:
        url = f"{self.base_url}/schedule/api/get-groups/"
        params = {"study_mode": study_mode, "course": course}
        response = await self._safe_get(url, params=params)
        if not response:
            return []
        try:
            data = response.json()
            if isinstance(data, dict) and "groups" in data:
                return data["groups"]
        except Exception:
            pass
        return []

    async def fetch_week_for_date(self, target_date: date, course: int = 2, study_mode: str = "Дневная") -> tuple[int | None, date]:
        url = f"{self.base_url}/schedule/api/get-week-for-date/"
        monday = target_date - timedelta(days=target_date.weekday())
        params = {"study_mode": study_mode, "course": course, "date": monday.strftime("%Y-%m-%d")}
        response = await self._safe_get(url, params=params)
        if not response:
            return None, monday
        try:
            data = response.json()
            week_data = data.get("week")
            if isinstance(week_data, dict):
                w_id = week_data.get("id")
                raw_start = week_data.get("start_date") or week_data.get("date_start") or week_data.get("start")
                actual_monday = monday
                if raw_start:
                    try:
                        actual_monday = date.fromisoformat(str(raw_start).split("T")[0])
                    except Exception:
                        actual_monday = monday
                if w_id:
                    return int(w_id), actual_monday

            week_id = data.get("week_id") or data.get("id")
            if week_id:
                return int(week_id), monday
        except Exception:
            pass
        return None, monday

    async def fetch_schedule(self, week_id: int, course: int = 2, study_mode: str = "Дневная") -> list[dict[str, Any]] | None:
        url = f"{self.base_url}/schedule/api/get-schedule/"
        params = {"study_mode": study_mode, "course": course, "week_id": week_id}
        response = await self._safe_get(url, params=params)
        if not response:
            return None
        try:
            data = response.json()
            if isinstance(data, dict) and "lessons" in data:
                return data["lessons"]
        except Exception:
            pass
        return None


api_client = BioBSUApiClient()


async def sync_groups_to_db(session: AsyncSession, course: int = 2, study_mode: str = "Дневная") -> int:
    raw_groups = await api_client.fetch_groups(course=course, study_mode=study_mode)
    if not raw_groups:
        return 0

    saved_count = 0
    for g_data in raw_groups:
        group_id = g_data.get("id")
        if not group_id:
            continue
        name = g_data.get("name", "")
        number = str(g_data.get("number") or "").strip()

        existing = await session.get(Group, group_id)
        if existing:
            existing.name = name
            existing.number = number
            existing.course = course
            existing.study_mode = study_mode
        else:
            session.add(Group(id=group_id, study_mode=study_mode, course=course, number=number, name=name))
        saved_count += 1

    await session.commit()
    logger.info(f"👥 Синхронизировано {saved_count} групп ({course} курс)")
    return saved_count


def calculate_schedule_diff(
    old_lessons: list[Lesson], 
    new_lessons: list[Lesson]
) -> dict[int, list[ScheduleChangeDTO]]:
    changes_by_group: dict[int, list[ScheduleChangeDTO]] = defaultdict(list)

    old_by_grp = defaultdict(dict)
    for l in old_lessons:
        key = (l.day, l.slot_id, l.subgroup)
        old_by_grp[l.group_id][key] = l

    new_by_grp = defaultdict(dict)
    for l in new_lessons:
        key = (l.day, l.slot_id, l.subgroup)
        new_by_grp[l.group_id][key] = l

    all_groups = set(old_by_grp.keys()) | set(new_by_grp.keys())

    for g_id in all_groups:
        old_dict = old_by_grp.get(g_id, {})
        new_dict = new_by_grp.get(g_id, {})

        # Если старых записей вообще не было (первый старт) — не спамим изменениями
        if not old_dict:
            continue

        all_keys = set(old_dict.keys()) | set(new_dict.keys())

        for (day, slot_id, subgroup) in all_keys:
            old_l = old_dict.get((day, slot_id, subgroup))
            new_l = new_dict.get((day, slot_id, subgroup))

            # 1. Отмена пары
            if old_l and not new_l:
                changes_by_group[g_id].append(
                    ScheduleChangeDTO(
                        day=day,
                        slot_id=slot_id,
                        subgroup=subgroup,
                        change_type="removed",
                        subject=old_l.subject,
                        lesson_type=old_l.lesson_type,
                        room=old_l.room,
                        teacher=old_l.teacher
                    )
                )
            # 2. Добавление новой пары
            elif not old_l and new_l:
                details = []
                if new_l.teacher:
                    details.append(f"Преп. {short_name(new_l.teacher)}")

                changes_by_group[g_id].append(
                    ScheduleChangeDTO(
                        day=day,
                        slot_id=slot_id,
                        subgroup=subgroup,
                        change_type="added",
                        subject=new_l.subject,
                        lesson_type=new_l.lesson_type,
                        room=new_l.room,
                        teacher=new_l.teacher,
                        details=details
                    )
                )
            # 3. Изменение существующей пары
            elif old_l and new_l:
                diffs = []
                if old_l.subject != new_l.subject:
                    diffs.append(f"Предмет: {old_l.subject} ➔ {new_l.subject}")
                if old_l.lesson_type != new_l.lesson_type:
                    diffs.append(f"Тип: {old_l.lesson_type} ➔ {new_l.lesson_type}")
                if (old_l.room or "—") != (new_l.room or "—"):
                    diffs.append(f"Ауд: {old_l.room or '—'} ➔ {new_l.room or '—'}")
                if (old_l.teacher or "—") != (new_l.teacher or "—"):
                    diffs.append(f"Преп: {short_name(old_l.teacher)} ➔ {short_name(new_l.teacher)}")

                if diffs:
                    changes_by_group[g_id].append(
                        ScheduleChangeDTO(
                            day=day,
                            slot_id=slot_id,
                            subgroup=subgroup,
                            change_type="modified",
                            subject=new_l.subject,
                            lesson_type=new_l.lesson_type,
                            room=new_l.room or old_l.room,
                            teacher=new_l.teacher or old_l.teacher,
                            details=diffs
                        )
                    )

    return changes_by_group


async def sync_schedule_to_db(
    session: AsyncSession, 
    valid_group_ids: set[int],
    target_date: date | None = None, 
    course: int = 2, 
    study_mode: str = "Дневная"
) -> tuple[int, dict[int, tuple[date, list[ScheduleChangeDTO]]]]:
    if target_date is None:
        target_date = get_current_date()

    monday = target_date - timedelta(days=target_date.weekday())
    week_id, actual_monday = await api_client.fetch_week_for_date(monday, course=course, study_mode=study_mode)
    if not week_id:
        return 0, {}

    # Сохраняем или обновляем дату недели в базе
    week_obj = await session.get(Week, week_id)
    if not week_obj:
        week_obj = Week(id=week_id, study_mode=study_mode, course=course, start_date=actual_monday)
        session.add(week_obj)
    else:
        week_obj.start_date = actual_monday
        week_obj.course = course
        week_obj.study_mode = study_mode
    
    await session.commit()

    raw_lessons = await api_client.fetch_schedule(week_id=week_id, course=course, study_mode=study_mode)
    
    if raw_lessons is None:
        logger.warning(f"⚠️ Не удалось получить расписание для week_id={week_id}. База не изменена")
        return 0, {}

    new_lessons = []
    for item in raw_lessons:
        raw_type = item.get("lesson_type", "other")
        discipline = item.get("discipline") or item.get("subject") or "Предмет не указан"
        teacher = item.get("teacher")
        room = item.get("room")
        address = item.get("address") or "Курчатова 10"
        
        subgroup_name = item.get("subgroup_name")
        subgroup = int(subgroup_name) if subgroup_name and str(subgroup_name).isdigit() else None

        group_ids = item.get("group_ids") or []
        if not group_ids and "group_id" in item:
            group_ids = [item["group_id"]]

        for g_id in group_ids:
            if g_id not in valid_group_ids:
                continue

            new_lessons.append(Lesson(
                group_id=g_id,
                week_id=week_id,
                day=int(item.get("day", 0)),
                slot_id=int(item.get("slot_id", 1)),
                subject=discipline,
                lesson_type=LESSON_TYPES_MAP.get(raw_type, "ДР"),
                teacher=teacher,
                room=room,
                address=address,
                subgroup=subgroup
            ))

    # Считываем старые занятия для поиска разницы
    old_lessons_res = await session.execute(select(Lesson).where(Lesson.week_id == week_id))
    old_lessons = old_lessons_res.scalars().all()

    # Вычисляем разницу
    diff_results = calculate_schedule_diff(old_lessons, new_lessons)
    formatted_diffs = {g_id: (actual_monday, changes) for g_id, changes in diff_results.items() if changes}

    # Если расписание не изменилось — не перезаписываем базу
    if old_lessons and not formatted_diffs and len(old_lessons) == len(new_lessons):
        return len(new_lessons), {}

    await session.execute(delete(Lesson).where(Lesson.week_id == week_id))
    
    if new_lessons:
        session.add_all(new_lessons)
        
    await session.commit()
    logger.info(f"✅ Обновлено {len(new_lessons)} пар ({course} курс, week_id={week_id})")

    return len(new_lessons), formatted_diffs


async def sync_all_courses(session: AsyncSession, target_date: date | None = None, bot=None) -> dict[str, Any]:
    if target_date is None:
        target_date = get_current_date()

    next_week = target_date + timedelta(days=7)
    after_next_week = target_date + timedelta(days=14)

    # 1. Синхронизируем группы (1 - 5 курс)
    for c in range(1, 6):
        try:
            await sync_groups_to_db(session, course=c)
            await asyncio.sleep(0.1)
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка синхронизации групп {c} курса: {e}")

    groups_res = await session.execute(select(Group.id))
    valid_group_ids = set(groups_res.scalars().all())

    # 2. Синхронизируем расписание по 5 курсам с мягкой паузой (0.25с)
    total_lessons = 0
    all_detected_changes: dict[tuple[int, date], list[ScheduleChangeDTO]] = defaultdict(list)

    for c in range(1, 6):
        for target_w in (target_date, next_week, after_next_week):
            try:
                count, diffs = await sync_schedule_to_db(session, valid_group_ids, target_date=target_w, course=c)
                total_lessons += count
                for g_id, (m, ch) in diffs.items():
                    if ch:
                        all_detected_changes[(g_id, m)].extend(ch)
                
                # Мягкая задержка между запросами для естественного поведения
                await asyncio.sleep(0.25)
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка синхронизации расписания {c} курса: {e}")

    # 3. Если передан bot и есть изменения — рассылаем уведомления
    if bot and all_detected_changes:
        asyncio.create_task(dispatch_schedule_changes(bot, dict(all_detected_changes)))

    now_str = get_minsk_now().strftime("%d.%m.%Y %H:%M:%S")
    unique_groups = list({g_id for g_id, _ in all_detected_changes.keys()})

    LAST_SYNC_INFO.update({
        "timestamp": now_str,
        "success": True,
        "errors": [],
        "total_lessons_saved": total_lessons,
        "changes_count": len(all_detected_changes),
        "changed_groups": unique_groups,
    })

    logger.info(f"Синхронизация завершена в {now_str}. Всего сохранено пар: {total_lessons}")
    return LAST_SYNC_INFO