"""
bot/main.py — Точка входа VPN-платформы.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from loguru import logger
from redis.asyncio import Redis

from bot.handlers import admin, buy, myvpn, start
from bot.middlewares.rate_limit import (
    BlockedUserMiddleware,
    DatabaseMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
)
from bot.tasks.scheduler import setup_scheduler
from config import settings
from database.session import check_db_connection, close_db


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        "logs/vpn_platform.log",
        level="DEBUG",
        rotation="100 MB",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )
    logger.add(
        "logs/errors.log",
        level="ERROR",
        rotation="50 MB",
        retention="90 days",
        compression="gz",
        enqueue=True,
    )


async def main() -> None:
    setup_logging()
    logger.info("🚀 Запуск VPN Platform Bot")

    if not await check_db_connection():
        logger.error("❌ Нет подключения к PostgreSQL")
        sys.exit(1)

    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

    try:
        await redis.ping()
        logger.info("✅ Redis подключён")
    except Exception as exc:
        logger.error(f"❌ Ошибка Redis: {exc}")
        sys.exit(1)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.message.middleware(RateLimitMiddleware(redis=redis))
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware(redis=redis))
    dp.callback_query.middleware(DatabaseMiddleware())

    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(myvpn.router)
    dp.include_router(admin.router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот запущен: @{bot_info.username}")

    # FIX: используем admin_ids_list вместо admin_ids (строки)
    # FIX: убран __import__("datetime") — используем нормальный импорт
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>VPN Platform запущен!</b>\n\n"
                f"🤖 Бот: @{bot_info.username}\n"
                f"📦 Окружение: {settings.environment}\n"
                f"🕐 Время: {now_str} UTC",
            )
        except Exception as exc:
            logger.warning(f"Не удалось уведомить admin={admin_id}: {exc}")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await redis.aclose()
        await close_db()
        await bot.session.close()
        logger.info("👋 VPN Platform остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Остановлен (Ctrl+C)")
    except Exception as exc:
        logger.critical(f"💥 Критическая ошибка: {exc}")
        sys.exit(1)
