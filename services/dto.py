from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True, frozen=True)
class GroupDTO:
    id: int
    course: int
    number: str
    name: str
    study_mode: str = "Дневная"


@dataclass(slots=True, frozen=True)
class WeekDTO:
    id: int
    course: int
    start_date: date
    study_mode: str = "Дневная"


@dataclass(slots=True, frozen=True)
class LessonDTO:
    id: int
    group_id: int
    week_id: int
    day: int
    slot_id: int
    subject: str
    lesson_type: str
    teacher: str | None = None
    room: str | None = None
    address: str | None = None
    subgroup: int | None = None


@dataclass(slots=True)
class TeacherSlotDTO:
    day: int
    slot_id: int
    subject: str
    lesson_type: str
    room: str | None
    address: str | None
    subgroup: int | None
    groups: list[str] = field(default_factory=list)
    groups_display: str = ""


@dataclass(slots=True)
class ScheduleChangeDTO:
    day: int
    slot_id: int
    subgroup: int | None
    change_type: str 
    subject: str
    lesson_type: str
    details: list[str] = field(default_factory=list)