import asyncio
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_BASE_URL, logger
from models import Group, Week, Lesson

LESSON_TYPES_MAP = {
    "lecture": "ЛК",
    "practice": "ПЗ",
    "lab": "ЛР",
    "seminar": "СМ",
    "other": "ДР"
}


def get_current_date() -> date:
    minsk_tz = timezone(timedelta(hours=3))
    return datetime.now(minsk_tz).date()


class BioBSUApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        # Очищаем базовый URL от завершающих слэшей во избежание // в путях
        self.base_url = base_url.rstrip("/")
        
        # Полный набор заголовков реального браузера для прохождения WAF/Nginx
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.base_url}/schedule/",
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Переиспользует единый клиент для поддержки Keep-Alive и cookies."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(15.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _safe_get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[httpx.Response]:
        client = await self.get_client()
        try:
            response = await client.get(url, params=params)
            if response.status_code == 403:
                logger.error(
                    f"403 Forbidden при запросе к {url}. Ответ сервера: {response.text[:250]}"
                )
                return None
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка {e.response.status_code} для {url}: {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Сетевая ошибка при запросе к {url}: {e}")
            return None

    async def fetch_groups(self, course: int = 2, study_mode: str = "Дневная") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/schedule/api/get-groups/"
        params = {"study_mode": study_mode, "course": course}
        
        response = await self._safe_get(url, params=params)
        if response:
            try:
                return response.json().get("groups", [])
            except Exception as e:
                logger.error(f"Ошибка парсинга JSON групп ({course} курс): {e}")
        return []

    async def fetch_week_for_date(self, target_date: date, course: int = 2, study_mode: str = "Дневная") -> Optional[int]:
        url = f"{self.base_url}/schedule/api/get-week-for-date/"
        monday = target_date - timedelta(days=target_date.weekday())
        params = {"study_mode": study_mode, "course": course, "date": monday.strftime("%Y-%m-%d")}

        response = await self._safe_get(url, params=params)
        if response:
            try:
                data = response.json()
                week_data = data.get("week")
                if isinstance(week_data, dict):
                    return week_data.get("id")
                return data.get("week_id") or data.get("id")
            except Exception as e:
                logger.error(f"Ошибка парсинга week_id для {monday}: {e}")
        return None

    async def fetch_schedule(self, week_id: int, course: int = 2, study_mode: str = "Дневная") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/schedule/api/get-schedule/"
        params = {"study_mode": study_mode, "course": course, "week_id": week_id}

        response = await self._safe_get(url, params=params)
        if response:
            try:
                return response.json().get("lessons", [])
            except Exception as e:
                logger.error(f"Ошибка парсинга расписания (week_id={week_id}): {e}")
        return []


api_client = BioBSUApiClient()


async def sync_groups_to_db(session: AsyncSession, course: int = 2, study_mode: str = "Дневная"):
    raw_groups = await api_client.fetch_groups(course=course, study_mode=study_mode)
    if not raw_groups:
        return

    for g_data in raw_groups:
        group_id = g_data.get("id")
        name = g_data.get("name", "")
        number = str(g_data.get("number") or "")

        existing = await session.get(Group, group_id)
        if existing:
            existing.name = name
            existing.number = number
            existing.course = course
            existing.study_mode = study_mode
        else:
            session.add(Group(id=group_id, study_mode=study_mode, course=course, number=number, name=name))

    await session.commit()
    logger.info(f"Синхронизировано {len(raw_groups)} групп ({course} курс).")


async def sync_schedule_to_db(session: AsyncSession, target_date: Optional[date] = None, course: int = 2, study_mode: str = "Дневная"):
    if target_date is None:
        target_date = get_current_date()

    monday = target_date - timedelta(days=target_date.weekday())
    week_id = await api_client.fetch_week_for_date(monday, course=course, study_mode=study_mode)
    if not week_id:
        return

    week_obj = await session.get(Week, week_id)
    if not week_obj:
        week_obj = Week(id=week_id, study_mode=study_mode, course=course, start_date=monday)
        session.add(week_obj)
        await session.commit()

    raw_lessons = await api_client.fetch_schedule(week_id=week_id, course=course, study_mode=study_mode)
    if not raw_lessons:
        return

    await session.execute(delete(Lesson).where(Lesson.week_id == week_id))

    new_lessons = []
    for item in raw_lessons:
        raw_type = item.get("lesson_type", "other")
        discipline = item.get("discipline") or "Предмет не указан"
        teacher = item.get("teacher")
        room = item.get("room")
        address = item.get("address") or "Курчатова 10"
        
        subgroup_name = item.get("subgroup_name")
        subgroup = int(subgroup_name) if subgroup_name and str(subgroup_name).isdigit() else None

        group_ids = item.get("group_ids") or []
        if not group_ids and "group_id" in item:
            group_ids = [item["group_id"]]

        for g_id in group_ids:
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

    session.add_all(new_lessons)
    await session.commit()
    logger.info(f"Сохранено {len(new_lessons)} пар ({course} курс, week_id={week_id}).")


async def sync_all_courses(session: AsyncSession, target_date: Optional[date] = None):
    if target_date is None:
        target_date = get_current_date()
        
    next_week = target_date + timedelta(days=7)
    after_next_week = target_date + timedelta(days=14)

    for c in range(1, 5):
        await sync_groups_to_db(session, course=c)
        await asyncio.sleep(0.3)
        
        await sync_schedule_to_db(session, target_date=target_date, course=c)
        await asyncio.sleep(0.3)
        
        await sync_schedule_to_db(session, target_date=next_week, course=c)
        await asyncio.sleep(0.3)

        await sync_schedule_to_db(session, target_date=after_next_week, course=c)
        await asyncio.sleep(0.3)