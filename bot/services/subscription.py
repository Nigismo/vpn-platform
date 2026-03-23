"""
bot/services/subscription.py — Сервис управления подписками.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import Subscription, SubscriptionStatus, User
from bot.services.marzban import MarzbanAPIError, generate_vpn_username, marzban_client
from bot.services.node_balancer import node_balancer


class SubscriptionService:

    async def create_subscription(
        self,
        session: AsyncSession,
        user: User,
        tariff_key: str,
    ) -> Subscription:
        tariff = settings.tariffs.get(tariff_key)
        if not tariff:
            raise ValueError(f"Неизвестный тариф: {tariff_key}")

        node = await node_balancer.get_best_node(session)
        if not node:
            raise RuntimeError("Нет доступных серверов. Попробуйте позже.")

        if not user.vpn_username:
            user.vpn_username = generate_vpn_username(user.id)

        duration_days = tariff["days"]
        expire_at = datetime.now(timezone.utc) + timedelta(days=duration_days)

        # FIX: используем user_exists() вместо голого try/except на любую ошибку
        try:
            user_exists = await marzban_client.user_exists(user.vpn_username)
        except MarzbanAPIError as exc:
            logger.error(f"Ошибка проверки пользователя Marzban: {exc}")
            raise RuntimeError(f"Ошибка VPN-сервера при проверке пользователя") from exc

        try:
            if user_exists:
                await marzban_client.update_user_expire(
                    user.vpn_username,
                    int(expire_at.timestamp()),
                )
            else:
                await marzban_client.create_user(
                    username=user.vpn_username,
                    expire_days=duration_days,
                    ip_limit=settings.vpn_ip_limit,
                    data_limit_gb=settings.vpn_default_traffic_gb,
                )
        except MarzbanAPIError as exc:
            logger.error(f"Ошибка Marzban при создании/обновлении пользователя: {exc}")
            raise RuntimeError(f"Ошибка VPN-сервера: {exc}") from exc

        # FIX: используем vpn_domains_list вместо vpn_domains (строки)
        domain = random.choice(settings.vpn_domains_list) if settings.vpn_domains_list else None
        sub_url = await marzban_client.get_subscription_url(user.vpn_username, domain)

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

        await node_balancer.increment_node_users(session, node.id)
        await session.flush()

        logger.info(
            f"✅ Подписка: user={user.id}, tariff={tariff_key}, "
            f"node={node.country}, expires={expire_at.date()}"
        )
        return subscription

    async def get_active_subscription(
        self, session: AsyncSession, user_id: int
    ) -> Optional[Subscription]:
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

    async def expire_subscription(self, session: AsyncSession, subscription: Subscription) -> None:
        subscription.status = SubscriptionStatus.EXPIRED

        result = await session.execute(select(User).where(User.id == subscription.user_id))
        user = result.scalar_one_or_none()

        if user and user.vpn_username:
            other = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.id != subscription.id,
                )
            )
            if not other.scalar_one_or_none():
                try:
                    await marzban_client.delete_user(user.vpn_username)
                except MarzbanAPIError as exc:
                    logger.warning(f"Ошибка удаления из Marzban: {exc}")

        if subscription.vpn_node_id:
            await node_balancer.decrement_node_users(session, subscription.vpn_node_id)

        logger.info(f"⏰ Подписка {subscription.id} деактивирована")

    async def add_bonus_days(
        self, session: AsyncSession, user_id: int, days: int, reason: str = ""
    ) -> bool:
        subscription = await self.get_active_subscription(session, user_id)
        if not subscription or not subscription.expires_at:
            return False

        subscription.expires_at += timedelta(days=days)

        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user and user.vpn_username:
            try:
                await marzban_client.update_user_expire(
                    user.vpn_username,
                    int(subscription.expires_at.timestamp()),
                )
            except MarzbanAPIError as exc:
                logger.error(f"Ошибка обновления expire в Marzban: {exc}")

        logger.info(f"🎁 +{days} дней для user={user_id}. {reason}")
        return True

    def format_subscription_info(self, subscription: Subscription) -> str:
        now = datetime.now(timezone.utc)
        expires = subscription.expires_at
        if expires:
            days_left = (expires - now).days
            expire_str = expires.strftime("%d.%m.%Y")
            emoji = "🟢" if days_left > 7 else ("🟡" if days_left > 2 else "🔴")
            return f"{emoji} До {expire_str} ({days_left} дней)"
        return "❓ Дата не установлена"


subscription_service = SubscriptionService()
