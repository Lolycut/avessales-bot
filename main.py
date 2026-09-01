import asyncio
import os
import random
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN, logger, get_minsk_now
from database import async_session_maker, engine
from models import Base
from services.api_client import sync_all_courses, api_client
from services.schedule_cache import schedule_cache
from services.notifications import morning_notifications_loop
from handlers import start, settings, schedule, admin, group_settings
from middlewares.metrics_middleware import MetricsMiddleware

# Настройки Webhook и сервера
WEBHOOK_PATH = "/webhook"
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL", "https://biobotm.onrender.com").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", None)
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 8080))

# Список фоновых задач для корректной остановки
background_tasks: list[asyncio.Task] = []


async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text="Webhook is edet! 🚀", status=200)


async def schedule_auto_sync_task(bot: Bot):
    while True:
        try:
            now = get_minsk_now()
            # Активные учебные часы: Пн-Сб с 07:30 до 20:00
            is_active_hours = (
                now.weekday() <= 5 and 
                (7 <= now.hour < 20 or (now.hour == 7 and now.minute >= 30))
            )
            
            # Рандомизация интервала
            if is_active_hours:
                interval = random.randint(240, 360)   # 4 - 6 минут
            else:
                interval = random.randint(1800, 2400) # 30 - 40 минут

            await asyncio.sleep(interval)
            
            async with async_session_maker() as session:
                res = await sync_all_courses(session, target_date=get_minsk_now().date(), bot=bot)
                if res.get("changes_count", 0) > 0:
                    await schedule_cache.reload_from_db(session)
                    logger.info(f"⚡ [Watchdog] Обнаружено и разослано {res['changes_count']} изменений в расписании!")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка фонового сторожа расписания: {e}")


async def on_startup(bot: Bot):
    logger.info("🔄 Инициализация приложения и загрузка данных...")
    
    # 1. Создание недостающих таблиц БД
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        # 2. Первичная синхронизация с сайтом при старте
        try:
            logger.info("🌐 Запрос свежих данных с bio.bsu.by...")
            await sync_all_courses(session, target_date=get_minsk_now().date(), bot=None)
            logger.info("✅ Первичная синхронизация с сайтом успешно завершена")
        except Exception as e:
            logger.warning(
                f"⚠️ Не удалось связаться с bio.bsu.by при старте: {e}. "
                f"Бот продолжит работу на существующих данных из PostgreSQL"
            )

        # 3. Загрузка In-Memory кэша
        try:
            await schedule_cache.reload_from_db(session)
            logger.info("🚀 In-Memory кэш успешно загружен из БД и готов к работе!")
        except Exception as e:
            logger.critical(f"❌ Критическая ошибка при чтении данных из БД в кэш: {e}")
            raise e

    # 4. Установка Webhook в Telegram
    webhook_url = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"
    logger.info(f"🌐 Установка вебхука на {webhook_url}...")
    await bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET
    )
    logger.info("✅ Вебхук успешно установлен в Telegram")

    # 5. Запуск фоновых задач
    sync_task = asyncio.create_task(schedule_auto_sync_task(bot))
    notify_task = asyncio.create_task(morning_notifications_loop(bot))
    background_tasks.extend([sync_task, notify_task])


async def on_shutdown(bot: Bot):
    logger.info("🛑 Остановка приложения, завершение фоновых задач...")

    # Отмена фоновых задач
    for task in background_tasks:
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    # Закрытие сессий и пулов
    await api_client.close()
    await bot.session.close()
    await engine.dispose()
    logger.info("✅ Все сетевые сессии и пулы соединений БД успешно закрыты")


def main():
    if not BOT_TOKEN:
        logger.critical("❌ Ошибка: BOT_TOKEN не задан в переменных окружения!")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Подключение системы сбора метрик
    metrics_mw = MetricsMiddleware()
    dp.message.middleware(metrics_mw)
    dp.callback_query.middleware(metrics_mw)

    # Регистрация хуков жизненного цикла aiogram
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Подключение роутеров
    dp.include_router(admin.router)
    dp.include_router(group_settings.router)
    dp.include_router(settings.router)
    dp.include_router(start.router)
    dp.include_router(schedule.router)

    # Инициализация веб-приложения aiohttp
    app = web.Application()

    # Healthcheck маршруты
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    # Регистрация обработчика входящих вебхуков aiogram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    logger.info(f"🚀 Запуск веб-сервера на порту {WEB_SERVER_PORT}...")
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот штатно остановлен")