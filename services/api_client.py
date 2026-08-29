import asyncio
import json
import os
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from config import API_BASE_URL, logger, ADMIN_IDS
from models import Group, Week, Lesson

LESSON_TYPES_MAP = {
    "lecture": "ЛК",
    "practice": "ПЗ",
    "lab": "ЛР",
    "seminar": "СМ",
    "other": "ДР"
}

FAILED_DUMP_PATH = "failed_api_response.json"

LAST_SYNC_INFO: Dict[str, Any] = {
    "timestamp": None,
    "success": True,
    "errors": [],
    "total_lessons_saved": 0,
    "last_error_details": None
}


def get_current_date() -> date:
    minsk_tz = timezone(timedelta(hours=3))
    return datetime.now(minsk_tz).date()


async def notify_admins(bot: Optional[Bot], message_text: str):
    if not bot or not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=message_text)
        except Exception as e:
            logger.warning(f"Не удалось отправить алерт админу {admin_id}: {e}")


class BioBSUApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.base_url}/schedule/",
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
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

    def _save_failed_payload(self, url: str, content: str, error_msg: str):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "error": error_msg,
            "raw_response": content
        }
        try:
            with open(FAILED_DUMP_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.warning(f"⚠️ Дамп ошибочного ответа сохранен в {FAILED_DUMP_PATH}")
        except Exception as e:
            logger.error(f"Не удалось записать дамп ошибки: {e}")

    async def _safe_get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[httpx.Response]:
        client = await self.get_client()
        try:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                err = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.error(f"Ошибка запроса к {url}: {err}")
                self._save_failed_payload(url, response.text, err)
                return None
            return response
        except Exception as e:
            err = f"Сетевое исключение: {str(e)}"
            logger.error(f"Сетевая ошибка при запросе к {url}: {err}")
            self._save_failed_payload(url, "", err)
            return None

    async def fetch_groups(self, course: int = 2, study_mode: str = "Дневная") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/schedule/api/get-groups/"
        params = {"study_mode": study_mode, "course": course}
        
        response = await self._safe_get(url, params=params)
        if not response:
            return []

        try:
            data = response.json()
            if isinstance(data, dict) and "groups" in data:
                return data["groups"]
            self._save_failed_payload(url, response.text, "Ключ 'groups' отсутствует в JSON")
        except Exception as e:
            logger.error(f"Ошибка парсинга JSON групп ({course} курс): {e}")
            self._save_failed_payload(url, response.text, f"JSONDecodeError: {e}")
        return []

    async def fetch_week_for_date(self, target_date: date, course: int = 2, study_mode: str = "Дневная") -> Optional[int]:
        url = f"{self.base_url}/schedule/api/get-week-for-date/"
        monday = target_date - timedelta(days=target_date.weekday())
        params = {"study_mode": study_mode, "course": course, "date": monday.strftime("%Y-%m-%d")}

        response = await self._safe_get(url, params=params)
        if not response:
            return None

        try:
            data = response.json()
            week_data = data.get("week")
            if isinstance(week_data, dict):
                return week_data.get("id")
            week_id = data.get("week_id") or data.get("id")
            if week_id:
                return int(week_id)
            self._save_failed_payload(url, response.text, "Не найден week_id в ответе")
        except Exception as e:
            logger.error(f"Ошибка парсинга week_id для {monday}: {e}")
            self._save_failed_payload(url, response.text, f"JSONDecodeError: {e}")
        return None

    async def fetch_schedule(self, week_id: int, course: int = 2, study_mode: str = "Дневная") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/schedule/api/get-schedule/"
        params = {"study_mode": study_mode, "course": course, "week_id": week_id}

        response = await self._safe_get(url, params=params)
        if not response:
            return []

        try:
            data = response.json()
            if isinstance(data, dict) and "lessons" in data:
                return data["lessons"]
            self._save_failed_payload(url, response.text, "Ключ 'lessons' отсутствует в JSON")
        except Exception as e:
            logger.error(f"Ошибка парсинга расписания (week_id={week_id}): {e}")
            self._save_failed_payload(url, response.text, f"JSONDecodeError: {e}")
        return []


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
        number = str(g_data.get("number") or "")

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
    return saved_count


async def sync_schedule_to_db(session: AsyncSession, target_date: Optional[date] = None, course: int = 2, study_mode: str = "Дневная") -> int:
    if target_date is None:
        target_date = get_current_date()

    monday = target_date - timedelta(days=target_date.weekday())
    week_id = await api_client.fetch_week_for_date(monday, course=course, study_mode=study_mode)
    if not week_id:
        return 0

    week_obj = await session.get(Week, week_id)
    if not week_obj:
        week_obj = Week(id=week_id, study_mode=study_mode, course=course, start_date=monday)
        session.add(week_obj)
        await session.commit()

    raw_lessons = await api_client.fetch_schedule(week_id=week_id, course=course, study_mode=study_mode)

    if not raw_lessons:
        logger.warning(f"⚠️ Ответ API пуст для курса {course}, week_id={week_id}. Старое расписание сохранено.")
        return 0

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

    if new_lessons:
        await session.execute(delete(Lesson).where(Lesson.week_id == week_id))
        session.add_all(new_lessons)
        await session.commit()

    return len(new_lessons)


async def sync_all_courses(session: AsyncSession, target_date: Optional[date] = None, bot: Optional[Bot] = None) -> Dict[str, Any]:
    global LAST_SYNC_INFO
    if target_date is None:
        target_date = get_current_date()
        
    next_week = target_date + timedelta(days=7)
    after_next_week = target_date + timedelta(days=14)

    total_lessons = 0
    errors = []

    for c in range(1, 5):
        try:
            await sync_groups_to_db(session, course=c)
            await asyncio.sleep(0.15)
            
            c_lessons = 0
            c_lessons += await sync_schedule_to_db(session, target_date=target_date, course=c)
            await asyncio.sleep(0.15)
            
            c_lessons += await sync_schedule_to_db(session, target_date=next_week, course=c)
            await asyncio.sleep(0.15)

            c_lessons += await sync_schedule_to_db(session, target_date=after_next_week, course=c)
            await asyncio.sleep(0.15)
            
            total_lessons += c_lessons
            if c_lessons == 0:
                errors.append(f"Курс {c}: API вернул 0 пар на все 3 недели")
        except Exception as e:
            err_msg = f"Курс {c}: Исключение при синхронизации — {str(e)}"
            logger.error(err_msg)
            errors.append(err_msg)

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    is_success = len(errors) == 0

    LAST_SYNC_INFO = {
        "timestamp": now_str,
        "success": is_success,
        "errors": errors,
        "total_lessons_saved": total_lessons,
        "last_error_details": "\n".join(errors) if errors else None
    }

    if not is_success and bot:
        alert_text = (
            f"🚨 <b>ВНИМАНИЕ! Ошибка синхронизации с bio.bsu.by!</b>\n\n"
            f"⏰ Время: <code>{now_str}</code>\n"
            f"❌ Обнаружено проблем: <b>{len(errors)}</b>\n\n"
            f"Детали:\n• " + "\n• ".join(errors[:5]) +
            f"\n\n💡 <i>Используйте /apidump для проверки структуры ответа.</i>"
        )
        await notify_admins(bot, alert_text)

    return LAST_SYNC_INFO