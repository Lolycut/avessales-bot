from dataclasses import dataclass
from typing import Optional
from cachetools import TTLCache
from sqlalchemy.ext.asyncio import AsyncSession
from models import User

@dataclass(slots=True)
class UserDTO:
    telegram_id: int
    first_name: str
    username: Optional[str]
    group_id: Optional[int]
    subgroup: Optional[int]
    notifications_enabled: bool


USER_CACHE: TTLCache = TTLCache(maxsize=10000, ttl=600)


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