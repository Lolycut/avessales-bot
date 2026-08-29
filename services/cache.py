from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Dict
from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, Group, Lesson, Week


# ==========================================
# ЧИСТЫЕ DTO
# ==========================================

@dataclass(slots=True)
class UserDTO:
    telegram_id: int
    first_name: str
    username: Optional[str]
    group_id: Optional[int]
    subgroup: Optional[int]
    notifications_enabled: bool


@dataclass(slots=True)
class GroupDTO:
    id: int
    study_mode: str
    course: int
    number: str
    name: str


@dataclass(slots=True)
class LessonDTO:
    group_id: int
    day: int
    slot_id: int
    subject: str
    lesson_type: str
    teacher: Optional[str]
    room: Optional[str]
    address: Optional[str]
    subgroup: Optional[int]


# ==========================================
# RAM-КЭШ ХРАНИЛИЩА
# ==========================================

USER_CACHE: TTLCache = TTLCache(maxsize=10000, ttl=600)
LESSONS_CACHE: Dict[tuple[int, date], List[LessonDTO]] = {}
GROUPS_CACHE: Dict[int, GroupDTO] = {}
TEACHERS_CACHE: List[str] = []


def invalidate_user_cache(user_id: int):
    USER_CACHE.pop(user_id, None)


async def get_cached_user(session: AsyncSession, user_id: int) -> Optional[UserDTO]:
    if user_id in USER_CACHE:
        return USER_CACHE[user_id]
    
    user = await session.get(User, user_id)
    if user:
        dto = UserDTO(
            telegram_id=user.telegram_id,
            first_name=user.first_name or "Студент",
            username=user.username,
            group_id=user.group_id,
            subgroup=user.subgroup,
            notifications_enabled=user.notifications_enabled
        )
        USER_CACHE[user_id] = dto
        return dto
    return None


async def get_cached_group(session: AsyncSession, group_id: int) -> Optional[GroupDTO]:
    if group_id in GROUPS_CACHE:
        return GROUPS_CACHE[group_id]
    
    group = await session.get(Group, group_id)
    if group:
        dto = GroupDTO(
            id=group.id,
            study_mode=group.study_mode,
            course=group.course,
            number=group.number,
            name=group.name
        )
        GROUPS_CACHE[group_id] = dto
        return dto
    return None


async def warm_up_schedule_cache(session: AsyncSession):
    global LESSONS_CACHE, GROUPS_CACHE, TEACHERS_CACHE

    groups_res = await session.execute(select(Group))
    groups = groups_res.scalars().all()
    GROUPS_CACHE = {
        g.id: GroupDTO(
            id=g.id,
            study_mode=g.study_mode,
            course=g.course,
            number=g.number,
            name=g.name
        ) 
        for g in groups
    }

    weeks_res = await session.execute(select(Week))
    weeks = weeks_res.scalars().all()

    new_lessons_cache = {}
    for w in weeks:
        lessons_res = await session.execute(select(Lesson).where(Lesson.week_id == w.id))
        all_lessons = lessons_res.scalars().all()

        all_dtos = [
            LessonDTO(
                group_id=l.group_id,
                day=l.day,
                slot_id=l.slot_id,
                subject=l.subject,
                lesson_type=l.lesson_type,
                teacher=l.teacher,
                room=l.room,
                address=l.address,
                subgroup=l.subgroup
            )
            for l in all_lessons
        ]

        for g_id in GROUPS_CACHE.keys():
            g_lessons = [dto for dto in all_dtos if dto.group_id == g_id]
            if g_lessons:
                new_lessons_cache[(g_id, w.start_date)] = g_lessons

    LESSONS_CACHE = new_lessons_cache

    teachers_res = await session.execute(
        select(Lesson.teacher).where(Lesson.teacher.is_not(None)).distinct()
    )
    TEACHERS_CACHE = [t for t in teachers_res.scalars().all() if t]