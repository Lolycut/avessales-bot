import asyncio
from datetime import date
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import os

from config import BOT_TOKEN, logger, get_minsk_now
from database import init_db, async_session_maker
from services.api_client import sync_all_courses
from services.notifications import morning_notifications_loop
from handlers import start, settings, schedule, admin

async def handle_ping(request):
    return web.Response(text="РАБОТАЕТ!")

async def start_dummy_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 7860))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web-сервер заглушка запущен на порту {port}")

async def schedule_auto_sync_task():
    while True:
        try:
            await asyncio.sleep(2 * 3600)
            logger.info("⏰ Фоновое автообновление расписания...")
            async with async_session_maker() as session:
                await sync_all_courses(session, target_date=get_minsk_now().date())
            logger.info("✅ Расписание успешно обновлено в фоне!")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка фонового обновления: {e}")

async def on_startup():
    logger.info("Инициализация таблиц БД...")
    await init_db()
    
    logger.info("Синхронизация данных...")
    async with async_session_maker() as session:
        await sync_all_courses(session, target_date=get_minsk_now().date())
    logger.info("База данных готова")

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(settings.router)
    dp.include_router(start.router)
    dp.include_router(schedule.router)

    await on_startup()
    await start_dummy_webserver()

    sync_task = asyncio.create_task(schedule_auto_sync_task())
    notify_task = asyncio.create_task(morning_notifications_loop(bot))

    logger.info("Бот запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        sync_task.cancel()
        notify_task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
