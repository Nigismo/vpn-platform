"""
bot/middlewares/rate_limit.py — Middleware для ограничения частоты запросов.
Защищает бота от спама через Redis rate limiting.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from loguru import logger
from redis.asyncio import Redis

from config import settings


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware ограничения запросов на основе Redis.
    Блокирует пользователей при превышении лимита сообщений.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.limit = settings.rate_limit_messages
        self.window = settings.rate_limit_window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Проверяем rate limit перед обработкой каждого сообщения."""

        # Достаём пользователя из события
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Ключ в Redis для этого пользователя
        key = f"rate_limit:{user.id}"

        # Получаем текущий счётчик
        current = await self.redis.get(key)
        current_count = int(current) if current else 0

        if current_count >= self.limit:
            # Превышен лимит — игнорируем запрос
            logger.warning(
                f"🚫 Rate limit: user {user.id} превысил лимит "
                f"({self.limit} сообщений за {self.window}с)"
            )
            if isinstance(event, Message):
                await event.answer(
                    f"⚠️ Слишком много запросов. Подождите {self.window} секунд."
                )
            return None

        # Увеличиваем счётчик
        pipe = self.redis.pipeline()
        pipe.incr(key)
        if current_count == 0:
            # Устанавливаем TTL только при первом запросе
            pipe.expire(key, self.window)
        await pipe.execute()

        return await handler(event, data)


class BlockedUserMiddleware(BaseMiddleware):
    """
    Middleware проверки блокировки пользователя.
    Заблокированные пользователи получают отказ в обслуживании.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Проверяем не заблокирован ли пользователь."""
        from database.session import get_session
        from database.models import User
        from sqlalchemy import select

        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Проверяем только реальных пользователей (не ботов)
        if user.is_bot:
            return None

        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.id == user.id)
            )
            db_user = result.scalar_one_or_none()

            if db_user and db_user.is_blocked:
                logger.info(f"🚫 Заблокированный пользователь {user.id} попытался взаимодействовать")
                if isinstance(event, Message):
                    await event.answer(
                        "🚫 Ваш аккаунт заблокирован. "
                        "Обратитесь в поддержку для разблокировки."
                    )
                return None

        return await handler(event, data)


class DatabaseMiddleware(BaseMiddleware):
    """
    Middleware для внедрения сессии БД в обработчики.
    Позволяет использовать session из data['session'] в хэндлерах.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Внедряем сессию БД в контекст обработчика."""
        from database.session import get_session

        async with get_session() as session:
            data["session"] = session
            return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования всех входящих сообщений.
    Упрощает отладку и мониторинг активности.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Логируем входящее событие."""
        user = data.get("event_from_user")
        if user and isinstance(event, Message):
            logger.debug(
                f"📨 Message от user={user.id} (@{user.username}): "
                f"{event.text[:50] if event.text else '[non-text]'}"
            )

        return await handler(event, data)
