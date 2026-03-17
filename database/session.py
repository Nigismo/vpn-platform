"""
database/session.py — Управление сессиями базы данных.
Создаёт асинхронный движок и фабрику сессий.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

# ----------------------------------------------------------
# Создаём асинхронный движок SQLAlchemy
# ----------------------------------------------------------
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=not settings.is_production,  # Логируем SQL-запросы в dev-режиме
    pool_size=20,                      # Размер пула соединений
    max_overflow=10,                   # Дополнительные соединения сверх пула
    pool_pre_ping=True,                # Проверяем соединение перед использованием
    pool_recycle=3600,                 # Переустанавливаем соединения каждый час
)

# ----------------------------------------------------------
# Фабрика асинхронных сессий
# ----------------------------------------------------------
AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,           # Не сбрасываем атрибуты после commit
    autoflush=True,
    autocommit=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Контекстный менеджер для получения сессии БД.
    Автоматически делает commit при успехе и rollback при ошибке.

    Использование:
        async with get_session() as session:
            result = await session.execute(select(User))
    """
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(f"Ошибка сессии БД, откатываем транзакцию: {exc}")
        raise
    finally:
        await session.close()


async def check_db_connection() -> bool:
    """
    Проверяем подключение к базе данных.
    Возвращает True если соединение успешно.
    """
    try:
        async with get_session() as session:
            await session.execute(
                __import__("sqlalchemy", fromlist=["text"]).text("SELECT 1")
            )
        logger.info("✅ Подключение к PostgreSQL успешно")
        return True
    except Exception as exc:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {exc}")
        return False


async def close_db() -> None:
    """Закрываем пул соединений при завершении приложения."""
    await engine.dispose()
    logger.info("🔌 Пул соединений PostgreSQL закрыт")
