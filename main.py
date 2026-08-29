import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, logger, get_minsk_now
from database import async_session_maker
from services.api_client import sync_all_courses, api_client
from services.cache import warm_up_schedule_cache
from services.notifications import morning_notifications_loop
from handlers import start, settings, schedule, admin


async def handle_ping(request):
    return web.Response(text="OK! Bot is healthy")


async def start_dummy_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 7860))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 веб-сервер успешно поднят на порту {port}")


async def schedule_auto_sync_task(bot: Bot):
    while True:
        try:
            await asyncio.sleep(2 * 3600)
            logger.info("⏰ Фоновое автообновление расписания с bio.bsu.by...")
            async with async_session_maker() as session:
                await sync_all_courses(session, target_date=get_minsk_now().date(), bot=bot)
                await warm_up_schedule_cache(session)
            logger.info("✅ Расписание успешно обновлено и закэшировано в RAM!")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка фонового обновления расписания: {e}")


async def on_startup(bot: Bot):
    logger.info("🔄 Первичная синхронизация данных с bio.bsu.by...")
    async with async_session_maker() as session:
        await sync_all_courses(session, target_date=get_minsk_now().date(), bot=bot)
        logger.info("⚡ Прогрев оперативного RAM-кэша...")
        await warm_up_schedule_cache(session)
        
    logger.info("🚀 Бот и RAM-кэш полностью готовы к работе!")


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(settings.router)
    dp.include_router(start.router)
    dp.include_router(schedule.router)

    await on_startup(bot)
    await start_dummy_webserver()

    sync_task = asyncio.create_task(schedule_auto_sync_task(bot))
    notify_task = asyncio.create_task(morning_notifications_loop(bot))

    logger.info("Бот успешно запущен в режиме Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("🛑 Остановка бота...")
        sync_task.cancel()
        notify_task.cancel()
        await api_client.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот штатно остановлен")