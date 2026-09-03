from datetime import date, datetime
from config import get_minsk_now
from sqlalchemy import BigInteger, ForeignKey, Index, SmallInteger, String, Boolean, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=False, index=True
    )
    study_mode: Mapped[str] = mapped_column(default="Дневная")
    course: Mapped[int] = mapped_column(SmallInteger, index=True)
    number: Mapped[str] = mapped_column(index=True)
    name: Mapped[str] = mapped_column()

    users: Mapped[list["User"]] = relationship(back_populates="group")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    chats: Mapped[list["Chat"]] = relationship(back_populates="group")


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True
    )
    username: Mapped[str | None] = mapped_column(default=None)
    first_name: Mapped[str] = mapped_column(default="Студент")
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), default=None, index=True
    )
    
    subgroup: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    specialization: Mapped[int | None] = mapped_column(SmallInteger, default=None)

    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    change_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(
        default=get_minsk_now, server_default=func.now()
    )

    group: Mapped["Group | None"] = relationship(back_populates="users")


class Chat(Base):
    __tablename__ = "chats"

    chat_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String, default=None)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), default=None, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # Чтение сообщений «Бот ...»
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # Утренние уведы в 07:45
    change_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # Уведы об изменениях
    created_at: Mapped[datetime] = mapped_column(
        default=get_minsk_now, server_default=func.now()
    )

    group: Mapped["Group | None"] = relationship(back_populates="chats")


class Week(Base):
    __tablename__ = "weeks"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=False, index=True
    )
    study_mode: Mapped[str] = mapped_column(default="Дневная")
    course: Mapped[int] = mapped_column(SmallInteger, index=True)
    start_date: Mapped[date] = mapped_column(index=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=get_minsk_now, server_default=func.now(), onupdate=get_minsk_now
    )

    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="week", cascade="all, delete-orphan"
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"), index=True)
    day: Mapped[int] = mapped_column(SmallInteger, index=True)
    slot_id: Mapped[int] = mapped_column(SmallInteger)
    subject: Mapped[str] = mapped_column()
    lesson_type: Mapped[str] = mapped_column()
    teacher: Mapped[str | None] = mapped_column(default=None, index=True)
    room: Mapped[str | None] = mapped_column(default=None)
    address: Mapped[str | None] = mapped_column(default=None)
    subgroup: Mapped[int | None] = mapped_column(SmallInteger, default=None)

    specialization_order: Mapped[int | None] = mapped_column(SmallInteger, default=None, nullable=True)
    common_discipline: Mapped[str | None] = mapped_column(String, default=None, nullable=True)

    group: Mapped["Group"] = relationship(back_populates="lessons")
    week: Mapped["Week"] = relationship(back_populates="lessons")

    __table_args__ = (Index("idx_lesson_lookup", "group_id", "week_id", "day"),)