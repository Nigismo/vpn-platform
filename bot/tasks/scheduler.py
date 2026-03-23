"""
bot/tasks/scheduler.py — Фоновые задачи на APScheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import settings
from database.models import Subscription, SubscriptionStatus, User, VpnNode
from database.session import get_session


async def check_expiring_subscriptions(bot) -> None:
    logger.info("⏰ Проверка истекающих подписок")
    now = datetime.now(timezone.utc)
    notifications_sent = 0

    async with get_session() as session:
        # FIX: используем notify_days_list вместо notify_days_before (строки)
        for days_before in settings.notify_days_list:
            target_time = now + timedelta(days=days_before)
            window_start = target_time - timedelta(hours=6)

            notified_field = (
                Subscription.notified_3_days
                if days_before == 3
                else Subscription.notified_1_day
            )

            result = await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.user))
                .where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at.between(window_start, target_time),
                    notified_field == False,
                )
            )
            subscriptions = result.scalars().all()

            for sub in subscriptions:
                if not sub.user or sub.user.is_blocked:
                    continue

                expires_str = sub.expires_at.strftime("%d.%m.%Y")
                days_text = "3 дня" if days_before == 3 else "1 день"

                text = (
                    f"⏰ <b>Ваша подписка скоро истекает!</b>\n\n"
                    f"Осталось: <b>{days_text}</b>\n"
                    f"Дата окончания: {expires_str}\n\n"
                    f"Продлите подписку командой /buy"
                )

                try:
                    await bot.send_message(sub.user_id, text, parse_mode="HTML")
                    notifications_sent += 1
                    if days_before == 3:
                        sub.notified_3_days = True
                    else:
                        sub.notified_1_day = True
                except Exception as exc:
                    logger.warning(f"Не удалось отправить уведомление user={sub.user_id}: {exc}")

    logger.info(f"✅ Уведомлений отправлено: {notifications_sent}")


async def cleanup_expired_subscriptions(bot) -> None:
    logger.info("🗑️ Очистка истёкших подписок")
    now = datetime.now(timezone.utc)
    cleaned = 0

    async with get_session() as session:
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.user))
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= now,
            )
        )
        expired_subs = result.scalars().all()

        from bot.services.subscription import subscription_service

        for sub in expired_subs:
            try:
                await subscription_service.expire_subscription(session, sub)
                cleaned += 1

                if sub.user and not sub.user.is_blocked:
                    try:
                        await bot.send_message(
                            sub.user_id,
                            "❌ <b>Ваша подписка истекла.</b>\n\nДля продолжения используйте /buy",
                            parse_mode="HTML",
                        )
                    except Exception as exc:
                        logger.warning(f"Не удалось уведомить user={sub.user_id}: {exc}")

            except Exception as exc:
                logger.error(f"Ошибка деактивации подписки {sub.id}: {exc}")

    logger.info(f"✅ Деактивировано подписок: {cleaned}")


async def sync_node_stats() -> None:
    logger.info("🔄 Синхронизация нод")

    async with get_session() as session:
        result = await session.execute(select(VpnNode))
        nodes = result.scalars().all()

        from bot.services.node_balancer import node_balancer

        for node in nodes:
            try:
                await node_balancer.sync_node_stats(session, node.id)
            except Exception as exc:
                logger.error(f"Ошибка синхронизации ноды {node.id}: {exc}")

    logger.info("✅ Синхронизация нод завершена")


async def monitor_node_load(bot) -> None:
    async with get_session() as session:
        from bot.services.node_balancer import node_balancer
        nodes_stats = await node_balancer.get_all_nodes_stats(session)

        for node in nodes_stats:
            if node["load_percent"] >= settings.node_alert_threshold:
                alert_text = (
                    f"🔴 <b>АЛЕРТ: Перегрузка ноды!</b>\n\n"
                    f"{node['emoji']} {node['country']} — {node['name']}\n"
                    f"Загрузка: <b>{node['load_percent']}%</b> "
                    f"({node['current_users']}/{node['max_users']})"
                )
                # FIX: используем admin_ids_list вместо admin_ids (строки)
                for admin_id in settings.admin_ids_list:
                    try:
                        await bot.send_message(admin_id, alert_text, parse_mode="HTML")
                    except Exception as exc:
                        logger.warning(f"Не удалось отправить алерт admin={admin_id}: {exc}")


def setup_scheduler(bot) -> AsyncIOScheduler:
    # FIX: единый timezone UTC везде
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        check_expiring_subscriptions,
        trigger=IntervalTrigger(hours=6),
        args=[bot],
        id="check_expiring",
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        cleanup_expired_subscriptions,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        args=[bot],
        id="cleanup_expired",
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        sync_node_stats,
        trigger=CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="sync_nodes",
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        monitor_node_load,
        trigger=IntervalTrigger(minutes=30),
        args=[bot],
        id="monitor_nodes",
        max_instances=1,
        misfire_grace_time=120,
    )

    logger.info("📅 Планировщик задач настроен")
    return scheduler
