from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL
from models import Base

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "ssl": "require"},
    pool_size=5,
    max_overflow=10,
    pool_timeout=15,
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
