from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    study_mode = Column(String(50), default="Дневная")
    course = Column(Integer, nullable=False, index=True)
    number = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)

    users = relationship("User", back_populates="group")
    lessons = relationship("Lesson", back_populates="group", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    subgroup = Column(Integer, nullable=True)  # 1, 2 или None (вся группа)
    notifications_enabled = Column(Boolean, default=True, index=True)
    registered_at = Column(DateTime(timezone=True), server_default=func.now())

    group = relationship("Group", back_populates="users")


class Week(Base):
    __tablename__ = "weeks"

    id = Column(Integer, primary_key=True, index=True)
    study_mode = Column(String(50), default="Дневная")
    course = Column(Integer, nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lessons = relationship("Lesson", back_populates="week", cascade="all, delete-orphan")


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    week_id = Column(Integer, ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Integer, nullable=False, index=True)
    slot_id = Column(Integer, nullable=False)
    subject = Column(String(255), nullable=False)
    lesson_type = Column(String(50), nullable=False)
    teacher = Column(String(255), nullable=True, index=True)
    room = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    subgroup = Column(Integer, nullable=True)

    group = relationship("Group", back_populates="lessons")
    week = relationship("Week", back_populates="lessons")

    __table_args__ = (
        Index("idx_lesson_lookup", "group_id", "week_id", "day"),
    )