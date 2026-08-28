from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import (
    BigInteger, Integer, String, Boolean, Date, DateTime, 
    ForeignKey, SmallInteger, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_mode: Mapped[str] = mapped_column(String(32), default="Дневная")
    course: Mapped[int] = mapped_column(SmallInteger, index=True)
    number: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))

    users: Mapped[List["User"]] = relationship(back_populates="group")
    lessons: Mapped[List["Lesson"]] = relationship(back_populates="group", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    subgroup: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    group: Mapped[Optional["Group"]] = relationship(back_populates="users")

class Week(Base):
    __tablename__ = "weeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_mode: Mapped[str] = mapped_column(String(32))
    course: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lessons: Mapped[List["Lesson"]] = relationship(back_populates="week", cascade="all, delete-orphan")

class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"))
    
    day: Mapped[int] = mapped_column(SmallInteger)
    slot_id: Mapped[int] = mapped_column(SmallInteger)
    
    subject: Mapped[str] = mapped_column(String(255))
    lesson_type: Mapped[str] = mapped_column(String(32))
    teacher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    room: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(255), default="Курчатова 10")
    subgroup: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)

    group: Mapped["Group"] = relationship(back_populates="lessons")
    week: Mapped["Week"] = relationship(back_populates="lessons")

    __table_args__ = (
        Index("idx_lessons_group_week_day", "group_id", "week_id", "day"),
    )