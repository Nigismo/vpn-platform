"""
bot/services/user_service.py — Сервис управления пользователями.
Регистрация, поиск, обновление данных пользователей.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Referral, Subscription, SubscriptionStatus, User
from config import settings


def generate_referral_code(length: int = 8) -> str:
    """Генерируем уникальный реферальный код из букв и цифр."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


class UserService:
    """Сервис для работы с пользователями Telegram."""

    async def get_or_create_user(
        self,
        session: AsyncSession,
        telegram_id: int,
        first_name: str,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        language_code: Optional[str] = None,
        referral_code: Optional[str] = None,
    ) -> tuple[User, bool]:
        """
        Получаем пользователя из БД или создаём нового.
        Возвращает (user, is_new) — объект и флаг нового пользователя.
        """
        # Ищем существующего пользователя
        result = await session.execute(
            select(User).where(User.id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user:
            # Обновляем актуальные данные
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            user.last_activity = datetime.now(timezone.utc)
            return user, False

        # Генерируем уникальный реферальный код
        ref_code = await self._generate_unique_referral_code(session)

        # Ищем реферера если передан код
        referrer = None
        if referral_code:
            referrer = await self.get_user_by_referral_code(session, referral_code)

        # Создаём нового пользователя
        user = User(
            id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            language_code=language_code,
            referral_code=ref_code,
            referred_by_id=referrer.id if referrer else None,
            last_activity=datetime.now(timezone.utc),
        )
        session.add(user)

        # Создаём реферальную связь
        if referrer:
            referral = Referral(
                referrer_id=referrer.id,
                referred_id=telegram_id,
                bonus_days=settings.referral_bonus_days,
            )
            session.add(referral)
            logger.info(
                f"👥 Новый реферал: user={telegram_id} пришёл от referrer={referrer.id}"
            )

        await session.flush()
        logger.info(f"✅ Новый пользователь зарегистрирован: {telegram_id} ({first_name})")

        return user, True

    async def get_user_by_referral_code(
        self, session: AsyncSession, code: str
    ) -> Optional[User]:
        """Находим пользователя по его реферальному коду."""
        result = await session.execute(
            select(User).where(User.referral_code == code.upper())
        )
        return result.scalar_one_or_none()

    async def get_user(
        self, session: AsyncSession, telegram_id: int
    ) -> Optional[User]:
        """Получаем пользователя по Telegram ID."""
        result = await session.execute(
            select(User).where(User.id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_referral_stats(
        self, session: AsyncSession, user_id: int
    ) -> dict:
        """
        Получаем статистику реферальной программы пользователя.
        Возвращает количество приглашённых и начисленные бонусы.
        """
        # Общее число приглашённых
        total_result = await session.execute(
            select(func.count(Referral.id)).where(Referral.referrer_id == user_id)
        )
        total_invited = total_result.scalar() or 0

        # Число реферов с выданным бонусом
        bonused_result = await session.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_id == user_id,
                Referral.bonus_granted == True,
            )
        )
        paid_referrals = bonused_result.scalar() or 0

        total_bonus_days = paid_referrals * settings.referral_bonus_days

        return {
            "total_invited": total_invited,
            "paid_referrals": paid_referrals,
            "total_bonus_days": total_bonus_days,
        }

    async def process_referral_bonus(
        self,
        session: AsyncSession,
        new_user_id: int,
    ) -> bool:
        """
        Начисляем бонус рефереру при первой оплате приглашённого.
        Вызывается при успешном платеже нового пользователя.
        """
        from bot.services.subscription import subscription_service

        # Ищем реферальную связь
        result = await session.execute(
            select(Referral).where(
                Referral.referred_id == new_user_id,
                Referral.bonus_granted == False,
            )
        )
        referral = result.scalar_one_or_none()

        if not referral:
            return False

        # Начисляем бонус рефереру
        success = await subscription_service.add_bonus_days(
            session,
            user_id=referral.referrer_id,
            days=settings.referral_bonus_days,
            reason=f"Реферал #{new_user_id} оплатил подписку",
        )

        if success:
            referral.bonus_granted = True
            referral.bonus_granted_at = datetime.now(timezone.utc)
            logger.info(
                f"🎁 Реферальный бонус начислен: referrer={referral.referrer_id}, "
                f"+{settings.referral_bonus_days} дней"
            )
            return True

        return False

    async def get_total_stats(self, session: AsyncSession) -> dict:
        """Получаем общую статистику платформы для администратора."""
        # Всего пользователей
        total_users = await session.execute(select(func.count(User.id)))

        # Активных подписок
        active_subs = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.ACTIVE
            )
        )

        return {
            "total_users": total_users.scalar() or 0,
            "active_subscriptions": active_subs.scalar() or 0,
        }

    async def _generate_unique_referral_code(self, session: AsyncSession) -> str:
        """Генерируем уникальный реферальный код, проверяя коллизии."""
        for _ in range(10):
            code = generate_referral_code()
            existing = await self.get_user_by_referral_code(session, code)
            if not existing:
                return code
        # Если за 10 попыток не нашли уникальный — добавляем цифры
        return generate_referral_code(length=12)

    async def block_user(
        self, session: AsyncSession, user_id: int, blocked: bool = True
    ) -> bool:
        """Блокируем или разблокируем пользователя."""
        user = await self.get_user(session, user_id)
        if not user:
            return False
        user.is_blocked = blocked
        action = "заблокирован" if blocked else "разблокирован"
        logger.info(f"🚫 Пользователь {user_id} {action}")
        return True


# Глобальный экземпляр сервиса пользователей
user_service = UserService()
