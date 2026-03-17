"""
bot/services/node_balancer.py — Балансировщик нагрузки VPN-нод.
Выбирает наименее загруженную активную ноду для нового пользователя.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import NodeStatus, VpnNode


class NodeBalancer:
    """
    Управляет распределением пользователей по VPN-нодам.
    Алгоритм: выбираем активную ноду с наименьшей загрузкой.
    """

    async def get_best_node(self, session: AsyncSession) -> Optional[VpnNode]:
        """
        Находим оптимальную ноду для нового пользователя.

        Алгоритм:
        1. Выбираем ноды со статусом ACTIVE
        2. Исключаем ноды с загрузкой >= NODE_FULL_THRESHOLD
        3. Сортируем по current_users (меньше = лучше)
        4. Возвращаем первую
        """
        result = await session.execute(
            select(VpnNode)
            .where(VpnNode.status.in_([NodeStatus.ACTIVE, NodeStatus.NEAR_CAPACITY]))
            .order_by(VpnNode.current_users.asc())
        )
        nodes = result.scalars().all()

        # Фильтруем полностью заполненные ноды
        available_nodes = [
            node for node in nodes
            if node.load_percent < settings.node_full_threshold
        ]

        if not available_nodes:
            logger.warning("⚠️ Нет доступных VPN-нод для нового пользователя!")
            return None

        best_node = available_nodes[0]
        logger.debug(
            f"🎯 Выбрана нода: {best_node.country} ({best_node.load_percent}% загрузка)"
        )
        return best_node

    async def increment_node_users(
        self, session: AsyncSession, node_id: int
    ) -> None:
        """
        Увеличиваем счётчик пользователей ноды и обновляем её статус.
        Вызывается при создании новой подписки.
        """
        # Получаем актуальные данные ноды
        result = await session.execute(
            select(VpnNode).where(VpnNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            logger.error(f"Нода {node_id} не найдена при increment")
            return

        node.current_users += 1
        node.status = self._calculate_node_status(node)

        logger.debug(
            f"📈 Нода {node.country}: {node.current_users}/{node.max_users} пользователей"
        )

        # Если нода перегружена — отправляем алерт
        if node.load_percent >= settings.node_alert_threshold:
            logger.warning(
                f"🔴 АЛЕРТ: Нода {node.name} ({node.country}) загружена на {node.load_percent}%"
            )

    async def decrement_node_users(
        self, session: AsyncSession, node_id: int
    ) -> None:
        """
        Уменьшаем счётчик пользователей ноды.
        Вызывается при удалении/истечении подписки.
        """
        result = await session.execute(
            select(VpnNode).where(VpnNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return

        node.current_users = max(0, node.current_users - 1)
        node.status = self._calculate_node_status(node)

        logger.debug(
            f"📉 Нода {node.country}: {node.current_users}/{node.max_users} пользователей"
        )

    async def sync_node_stats(self, session: AsyncSession, node_id: int) -> None:
        """
        Синхронизируем реальное количество пользователей с Marzban.
        Запускается планировщиком раз в сутки.
        """
        from bot.services.marzban import MarzbanClient
        from database.models import Subscription, SubscriptionStatus

        result = await session.execute(
            select(VpnNode).where(VpnNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return

        # Считаем активные подписки на эту ноду в нашей БД
        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.vpn_node_id == node_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        real_count = len(sub_result.scalars().all())

        if node.current_users != real_count:
            logger.info(
                f"🔄 Синхронизация ноды {node.country}: "
                f"{node.current_users} → {real_count} пользователей"
            )
            node.current_users = real_count
            node.status = self._calculate_node_status(node)

    def _calculate_node_status(self, node: VpnNode) -> str:
        """Вычисляем статус ноды по проценту загрузки."""
        load = node.load_percent

        if load >= settings.node_full_threshold:
            return NodeStatus.FULL
        elif load >= settings.node_near_capacity_threshold:
            return NodeStatus.NEAR_CAPACITY
        else:
            return NodeStatus.ACTIVE

    async def get_all_nodes_stats(self, session: AsyncSession) -> list[dict]:
        """Получаем статистику всех нод для мониторинга."""
        result = await session.execute(select(VpnNode).order_by(VpnNode.country))
        nodes = result.scalars().all()

        return [
            {
                "id": node.id,
                "name": node.name,
                "country": node.country,
                "emoji": node.country_emoji,
                "ip": node.ip_address,
                "current_users": node.current_users,
                "max_users": node.max_users,
                "load_percent": node.load_percent,
                "status": node.status,
            }
            for node in nodes
        ]


# Глобальный экземпляр балансировщика
node_balancer = NodeBalancer()
