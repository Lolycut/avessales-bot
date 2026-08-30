import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, logger, get_minsk_now
from database import async_session_maker, engine
from models import Base
from services.api_client import sync_all_courses, api_client
from services.schedule_cache import schedule_cache
from services.notifications import morning_notifications_loop
from handlers import start, settings, schedule, admin, group_settings


async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text="OK!")


async def start_dummy_webserver() -> web.AppRunner | None:
    try:
        app = web.Application()
        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(os.getenv("PORT", 7860))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"🌐 Веб-сервер успешно запущен на порту {port}")
        return runner
    except Exception as e:
        logger.warning(f"⚠️ Не удалось запустить dummy веб-сервер (не критично для Polling): {e}")
        return None


async def schedule_auto_sync_task(bot: Bot):
    while True:
        try:
            await asyncio.sleep(2 * 3600)
            logger.info("⏰ Запуск периодического автообновления расписания...")
            async with async_session_maker() as session:
                await sync_all_courses(session, target_date=get_minsk_now().date(), bot=bot)
                await schedule_cache.reload_from_db(session)
            logger.info("✅ Фоновое расписание успешно обновлено в БД и кэше!")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка фонового обновления расписания: {e}")


async def on_startup(bot: Bot):
    logger.info("🔄 Инициализация приложения и загрузка данных...")
    
    # 0. Автоматическое создание недостающих таблиц (chats)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        # 1. Синхронизация с сайтом
        try:
            logger.info("🌐 Запрос свежих данных с bio.bsu.by...")
            await sync_all_courses(session, target_date=get_minsk_now().date(), bot=bot)
            logger.info("✅ Первичная синхронизация с сайтом успешно завершена.")
        except Exception as e:
            logger.warning(
                f"⚠️ Не удалось связаться с bio.bsu.by при старте: {e}. "
                f"Бот продолжит работу на существующих данных из PostgreSQL."
            )

        # 2. Загрузка In-Memory кэша
        try:
            await schedule_cache.reload_from_db(session)
            logger.info("🚀 In-Memory кэш успешно загружен из БД и готов к работе!")
        except Exception as e:
            logger.critical(f"❌ Критическая ошибка при чтении данных из БД в кэш: {e}")
            raise e


async def main():
    if not BOT_TOKEN:
        logger.critical("❌ Ошибка: BOT_TOKEN не задан в переменных окружения!")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Подключение роутеров в строгом приоритетном порядке
    dp.include_router(admin.router)
    dp.include_router(group_settings.router)
    dp.include_router(settings.router)
    dp.include_router(start.router)
    dp.include_router(schedule.router)

    # Инициализация кэша и веб-сервера
    await on_startup(bot)
    web_runner = await start_dummy_webserver()

    # Запуск фоновых задач
    sync_task = asyncio.create_task(schedule_auto_sync_task(bot))
    notify_task = asyncio.create_task(morning_notifications_loop(bot))

    logger.info("Бот успешно запущен в режиме Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("🛑 Остановка бота, завершение фоновых задач и освобождение ресурсов...")
        
        sync_task.cancel()
        notify_task.cancel()
        await asyncio.gather(sync_task, notify_task, return_exceptions=True)

        if web_runner:
            await web_runner.cleanup()
        await api_client.close()
        await bot.session.close()
        await engine.dispose()
        logger.info("✅ Все сетевые сессии и пулы соединений БД успешно закрыты")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот штатно остановлен")