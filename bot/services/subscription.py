"""
bot/services/subscription.py — Сервис управления подписками.
Создание, продление, удаление VPN-подписок.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import Subscription, SubscriptionStatus, User, VpnNode
from bot.services.marzban import generate_vpn_username, marzban_client
from bot.services.node_balancer import node_balancer


class SubscriptionService:
    """Управляет жизненным циклом подписок пользователей."""

    async def create_subscription(
        self,
        session: AsyncSession,
        user: User,
        tariff_key: str,
    ) -> Subscription:
        """
        Создаём новую VPN-подписку для пользователя.

        Шаги:
        1. Выбираем наименее загруженную ноду
        2. Генерируем VPN логин
        3. Создаём пользователя в Marzban
        4. Сохраняем подписку в БД
        5. Обновляем счётчик ноды
        """
        tariff = settings.tariffs.get(tariff_key)
        if not tariff:
            raise ValueError(f"Неизвестный тариф: {tariff_key}")

        # Шаг 1: Выбираем ноду
        node = await node_balancer.get_best_node(session)
        if not node:
            raise RuntimeError("Нет доступных серверов. Попробуйте позже.")

        # Шаг 2: Генерируем VPN логин (если ещё нет)
        if not user.vpn_username:
            user.vpn_username = generate_vpn_username(user.id)

        duration_days = tariff["days"]
        expire_at = datetime.now(timezone.utc) + timedelta(days=duration_days)

        # Шаг 3: Создаём пользователя в Marzban (или обновляем expire)
        try:
            # Проверяем, есть ли уже пользователь в Marzban
            try:
                existing = await marzban_client.get_user(user.vpn_username)
                # Пользователь уже есть — продлеваем подписку
                await marzban_client.update_user_expire(
                    user.vpn_username,
                    int(expire_at.timestamp()),
                )
                logger.info(f"🔄 Продлена подписка Marzban для {user.vpn_username}")
            except Exception:
                # Пользователя нет — создаём нового
                await marzban_client.create_user(
                    username=user.vpn_username,
                    expire_days=duration_days,
                    ip_limit=settings.vpn_ip_limit,
                    data_limit_gb=settings.vpn_default_traffic_gb,
                )

        except Exception as exc:
            logger.error(f"❌ Ошибка создания пользователя Marzban: {exc}")
            raise RuntimeError(f"Ошибка VPN-сервера: {exc}") from exc

        # Шаг 4: Генерируем ссылку подписки с ротацией домена
        domain = random.choice(settings.vpn_domains) if settings.vpn_domains else None
        sub_url = await marzban_client.get_subscription_url(user.vpn_username, domain)

        # Шаг 5: Сохраняем подписку в БД
        subscription = Subscription(
            user_id=user.id,
            tariff_key=tariff_key,
            duration_days=duration_days,
            status=SubscriptionStatus.ACTIVE,
            starts_at=datetime.now(timezone.utc),
            expires_at=expire_at,
            vpn_node_id=node.id,
            subscription_url=sub_url,
        )
        session.add(subscription)

        # Шаг 6: Обновляем счётчик пользователей ноды
        await node_balancer.increment_node_users(session, node.id)

        await session.flush()  # Получаем ID подписки до commit
        logger.info(
            f"✅ Подписка создана: user={user.id}, tariff={tariff_key}, "
            f"node={node.country}, expires={expire_at.date()}"
        )

        return subscription

    async def get_active_subscription(
        self, session: AsyncSession, user_id: int
    ) -> Optional[Subscription]:
        """Получаем активную подписку пользователя."""
        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > datetime.now(timezone.utc),
            )
            .order_by(Subscription.expires_at.desc())
        )
        return result.scalar_one_or_none()

    async def expire_subscription(
        self, session: AsyncSession, subscription: Subscription
    ) -> None:
        """
        Деактивируем истёкшую подписку.
        Удаляем пользователя из Marzban, освобождаем слот ноды.
        """
        subscription.status = SubscriptionStatus.EXPIRED

        # Получаем пользователя для удаления из Marzban
        result = await session.execute(
            select(User).where(User.id == subscription.user_id)
        )
        user = result.scalar_one_or_none()

        if user and user.vpn_username:
            # Проверяем, нет ли других активных подписок
            other_subs = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.id != subscription.id,
                )
            )
            if not other_subs.scalar_one_or_none():
                # Других активных подписок нет — удаляем из Marzban
                try:
                    await marzban_client.delete_user(user.vpn_username)
                except Exception as exc:
                    logger.warning(f"Ошибка удаления пользователя Marzban: {exc}")

        # Освобождаем слот на ноде
        if subscription.vpn_node_id:
            await node_balancer.decrement_node_users(session, subscription.vpn_node_id)

        logger.info(f"⏰ Подписка {subscription.id} истекла и деактивирована")

    async def add_bonus_days(
        self,
        session: AsyncSession,
        user_id: int,
        days: int,
        reason: str = "",
    ) -> bool:
        """
        Добавляем бонусные дни к активной подписке.
        Используется для реферальной программы и ручного начисления.
        """
        subscription = await self.get_active_subscription(session, user_id)
        if not subscription or not subscription.expires_at:
            logger.warning(
                f"Не удалось добавить бонус: нет активной подписки для user={user_id}"
            )
            return False

        # Продлеваем дату истечения
        subscription.expires_at += timedelta(days=days)

        # Обновляем expire в Marzban
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user and user.vpn_username:
            try:
                await marzban_client.update_user_expire(
                    user.vpn_username,
                    int(subscription.expires_at.timestamp()),
                )
            except Exception as exc:
                logger.error(f"Ошибка обновления expire в Marzban: {exc}")

        logger.info(
            f"🎁 Добавлено {days} бонусных дней для user={user_id}. Причина: {reason}"
        )
        return True

    def format_subscription_info(self, subscription: Subscription) -> str:
        """Форматируем информацию о подписке для отображения в боте."""
        now = datetime.now(timezone.utc)
        expires = subscription.expires_at

        if expires:
            days_left = (expires - now).days
            expire_str = expires.strftime("%d.%m.%Y")
            days_emoji = "🟢" if days_left > 7 else ("🟡" if days_left > 2 else "🔴")
            expire_info = f"{days_emoji} До {expire_str} ({days_left} дней)"
        else:
            expire_info = "❓ Дата не установлена"

        return expire_info


# Глобальный экземпляр сервиса подписок
subscription_service = SubscriptionService()
