import os
import logging
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

# Секреты
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
raw_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]

# База данных
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432) or 5432)
DB_NAME = os.getenv("DB_NAME", "bio_schedule_db")

DATABASE_URL = URL.create(
    drivername="postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME
)

API_BASE_URL = "https://bio.bsu.by"

MINSK_TZ = ZoneInfo("Europe/Minsk")

def get_minsk_now() -> datetime:
  return datetime.now(MINSK_TZ).replace(tzinfo=None)

# Логирование
LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
logger = logging.getLogger("BioBot")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

logger.addHandler(file_handler)
logger.addHandler(console_handler)