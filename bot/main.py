"""
bot/main.py — Точка входа VPN-платформы.
Инициализирует бота, middleware, роутеры и фоновые задачи.
"""

from __future__ import annotations

import asyncio
import sys

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


# ----------------------------------------------------------
# Настройка логирования через Loguru
# ----------------------------------------------------------
def setup_logging() -> None:
    """Конфигурируем loguru для продакшен-логирования."""
    logger.remove()  # Удаляем стандартный обработчик

    # Консоль
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # Файл — все логи
    logger.add(
        "logs/vpn_platform.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="100 MB",
        retention="30 days",
        compression="gz",
        enqueue=True,  # Асинхронная запись
    )

    # Файл — только ошибки
    logger.add(
        "logs/errors.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="50 MB",
        retention="90 days",
        compression="gz",
        enqueue=True,
    )

    logger.info("✅ Логирование настроено")


# ----------------------------------------------------------
# Основная функция запуска
# ----------------------------------------------------------
async def main() -> None:
    """Запускаем VPN-платформу."""
    setup_logging()

    logger.info("🚀 Запуск VPN Platform Bot")
    logger.info(f"📦 Окружение: {settings.environment}")

    # ----------------------------------------------------------
    # Проверяем подключение к базе данных
    # ----------------------------------------------------------
    if not await check_db_connection():
        logger.error("❌ Не удалось подключиться к PostgreSQL. Завершаем работу.")
        sys.exit(1)

    # ----------------------------------------------------------
    # Настраиваем Redis для хранения FSM-состояний и rate limiting
    # ----------------------------------------------------------
    redis = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        await redis.ping()
        logger.info("✅ Подключение к Redis успешно")
    except Exception as exc:
        logger.error(f"❌ Ошибка подключения к Redis: {exc}")
        sys.exit(1)

    # ----------------------------------------------------------
    # Инициализируем бота и диспетчер
    # ----------------------------------------------------------
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # FSM хранилище в Redis (сохраняется при перезапуске)
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    # ----------------------------------------------------------
    # Регистрируем middleware (порядок важен!)
    # ----------------------------------------------------------
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.message.middleware(RateLimitMiddleware(redis=redis))
    dp.message.middleware(DatabaseMiddleware())

    dp.callback_query.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware(redis=redis))
    dp.callback_query.middleware(DatabaseMiddleware())

    # ----------------------------------------------------------
    # Регистрируем роутеры
    # ----------------------------------------------------------
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(myvpn.router)
    dp.include_router(admin.router)

    logger.info("✅ Роутеры зарегистрированы")

    # ----------------------------------------------------------
    # Запускаем планировщик фоновых задач
    # ----------------------------------------------------------
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("✅ Планировщик запущен")

    # ----------------------------------------------------------
    # Уведомляем администраторов о запуске
    # ----------------------------------------------------------
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот запущен: @{bot_info.username}")

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>VPN Platform запущен!</b>\n\n"
                f"🤖 Бот: @{bot_info.username}\n"
                f"📦 Окружение: {settings.environment}\n"
                f"🕐 Время: {__import__('datetime').datetime.now().strftime('%d.%m.%Y %H:%M')}",
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Запускаем polling
    # ----------------------------------------------------------
    try:
        logger.info("🔄 Запуск polling...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except Exception as exc:
        logger.error(f"❌ Ошибка polling: {exc}")
        raise
    finally:
        # Корректно завершаем работу
        scheduler.shutdown(wait=False)
        await redis.aclose()
        await close_db()
        await bot.session.close()
        logger.info("👋 VPN Platform остановлен")


# ----------------------------------------------------------
# Точка входа
# ----------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал завершения (Ctrl+C)")
    except Exception as exc:
        logger.critical(f"💥 Критическая ошибка: {exc}")
        sys.exit(1)
