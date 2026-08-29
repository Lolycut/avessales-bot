from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL
from models import Base

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,         
    max_overflow=20,      
    pool_timeout=10,       
    pool_pre_ping=True,   
    pool_recycle=300       
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
