from datetime import date, datetime
from collections import defaultdict
from typing import Any
from config import get_minsk_now


class MetricsService:
    def __init__(self) -> None:
        self._current_date: date = get_minsk_now().date()
        self._boot_time: datetime = get_minsk_now()

        # Суточные метрики (сбрасываются в полночь по Минску)
        self._daily_unique_users: set[int] = set()
        self._daily_unique_chats: set[int] = set()
        self._daily_requests: int = 0
        self._daily_hourly_distribution: dict[int, int] = defaultdict(int)

        # Общие метрики с момента запуска
        self._total_requests: int = 0
        self._total_private_requests: int = 0
        self._total_group_requests: int = 0
        self._total_messages: int = 0
        self._total_callbacks: int = 0

    def _check_and_rollover_day(self) -> None:
        today = get_minsk_now().date()
        if today != self._current_date:
            self._current_date = today
            self._daily_unique_users.clear()
            self._daily_unique_chats.clear()
            self._daily_requests = 0
            self._daily_hourly_distribution.clear()

    def track(
        self,
        user_id: int | None,
        chat_id: int | None,
        chat_type: str,
        is_callback: bool = False
    ) -> None:
        self._check_and_rollover_day()
        now = get_minsk_now()

        self._total_requests += 1
        self._daily_requests += 1
        self._daily_hourly_distribution[now.hour] += 1

        if user_id:
            self._daily_unique_users.add(user_id)

        if chat_type in ("group", "supergroup") and chat_id:
            self._daily_unique_chats.add(chat_id)
            self._total_group_requests += 1
        else:
            self._total_private_requests += 1

        if is_callback:
            self._total_callbacks += 1
        else:
            self._total_messages += 1

    def get_stats(self) -> dict[str, Any]:
        self._check_and_rollover_day()

        peak_hour_str = "—"
        if self._daily_hourly_distribution:
            peak_hour, peak_count = max(self._daily_hourly_distribution.items(), key=lambda x: x[1])
            peak_hour_str = f"{peak_hour:02d}:00–{peak_hour:02d}:59 ({peak_count} запр.)"

        return {
            "boot_time": self._boot_time.strftime("%d.%m.%Y %H:%M"),
            "today_date": self._current_date.strftime("%d.%m.%Y"),
            "dau": len(self._daily_unique_users),
            "dac": len(self._daily_unique_chats),
            "daily_requests": self._daily_requests,
            "peak_hour": peak_hour_str,
            "total_requests": self._total_requests,
            "total_private": self._total_private_requests,
            "total_group": self._total_group_requests,
            "total_messages": self._total_messages,
            "total_callbacks": self._total_callbacks,
        }


metrics_service = MetricsService()