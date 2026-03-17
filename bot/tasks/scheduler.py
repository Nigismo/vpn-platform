"""
bot/tasks/scheduler.py — Фоновые задачи на APScheduler.
Проверка истекающих подписок, уведомления, синхронизация нод.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import select

from config import settings
from database.models import Subscription, SubscriptionStatus, User, VpnNode
from database.session import get_session

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def check_expiring_subscriptions(bot: Bot) -> None:
    """Каждые 6 часов: уведомляем о скором истечении подписки."""
    logger.info("Задача: проверка истекающих подписок")
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        for days_before in settings.notify_days_before:
            notify_from = now + timedelta(days=days_before)
            notify_to = notify_from + timedelta(hours=6)

            result = await session.execute(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at >= notify_from,
                    Subscription.expires_at <= notify_to,
                )
            )
            subscriptions = result.scalars().all()

            for sub in subscriptions:
                already_notified = (
                    sub.notified_3_days if days_before == 3 else sub.notified_1_day
                )
                if already_notified:
                    continue

                user_result = await session.execute(
                    select(User).where(User.id == sub.user_id)
                )
                user = user_result.scalar_one_or_none()
                if not user or user.is_blocked:
                    continue

                await _send_expiry_notification(bot, user.id, sub, days_before)

                if days_before == 3:
                    sub.notified_3_days = True
                else:
                    sub.notified_1_day = True

    logger.info("Задача проверки истекающих подписок завершена")


async def _send_expiry_notification(
    bot: Bot, user_id: int, subscription: Subscription, days_left: int
) -> None:
    """Отправляем уведомление об истечении подписки."""
    expire_str = subscription.expires_at.strftime("%d.%m.%Y")
    if days_left > 1:
        text = (
            f"⚠️ <b>Подписка истекает через {days_left} дня!</b>\n\n"
            f"📅 Дата: {expire_str}\n\n"
            f"🔄 Продлите сейчас, чтобы не терять доступ к VPN."
        )
    else:
        text = (
            f"🔴 <b>Подписка истекает ЗАВТРА!</b>\n\n"
            f"📅 Дата: {expire_str}\n\n"
            f"⚡ Продлите прямо сейчас!"
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Продлить подписку", callback_data="vpn:renew")
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception as exc:
        logger.warning(f"Не удалось отправить уведомление user={user_id}: {exc}")


async def remove_expired_subscriptions() -> None:
    """Ежедневно: деактивируем истёкшие подписки и удаляем из Marzban."""
    logger.info("Задача: удаление истёкших подписок")
    now = datetime.now(timezone.utc)
    count = 0

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= now,
            )
        )
        expired_subs = result.scalars().all()

        from bot.services.subscription import subscription_service
        for sub in expired_subs:
            try:
                await subscription_service.expire_subscription(session, sub)
                count += 1
            except Exception as exc:
                logger.error(f"Ошибка деактивации подписки {sub.id}: {exc}")

    logger.info(f"Деактивировано истёкших подписок: {count}")


async def sync_node_stats() -> None:
    """Ежедневно: синхронизируем счётчики нод с реальными данными БД."""
    logger.info("Задача: синхронизация статистики нод")
    async with get_session() as session:
        result = await session.execute(select(VpnNode))
        nodes = result.scalars().all()
        from bot.services.node_balancer import node_balancer
        for node in nodes:
            try:
                await node_balancer.sync_node_stats(session, node.id)
            except Exception as exc:
                logger.error(f"Ошибка синхронизации ноды {node.id}: {exc}")
    logger.info("Синхронизация нод завершена")


async def monitor_node_load(bot: Bot) -> None:
    """Каждые 30 минут: алерт администраторам при перегрузке нод."""
    async with get_session() as session:
        from bot.services.node_balancer import node_balancer
        nodes_stats = await node_balancer.get_all_nodes_stats(session)
        for node in nodes_stats:
            if node["load_percent"] >= settings.node_alert_threshold:
                alert_text = (
                    f"🔴 <b>АЛЕРТ: Перегрузка сервера!</b>\n\n"
                    f"{node['emoji']} <b>{node['country']}</b> — {node['ip']}\n"
                    f"Нагрузка: <b>{node['load_percent']}%</b> "
                    f"({node['current_users']}/{node['max_users']})"
                )
                for admin_id in settings.admin_ids:
                    try:
                        await bot.send_message(admin_id, alert_text, parse_mode="HTML")
                    except Exception:
                        pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Регистрируем все задачи и возвращаем готовый планировщик."""
    scheduler.add_job(
        check_expiring_subscriptions,
        trigger="interval",
        hours=6,
        kwargs={"bot": bot},
        id="check_expiring",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        remove_expired_subscriptions,
        trigger="cron",
        hour=2,
        minute=0,
        id="remove_expired",
        replace_existing=True,
    )
    scheduler.add_job(
        sync_node_stats,
        trigger="cron",
        hour=3,
        minute=0,
        id="sync_nodes",
        replace_existing=True,
    )
    scheduler.add_job(
        monitor_node_load,
        trigger="interval",
        minutes=30,
        kwargs={"bot": bot},
        id="monitor_nodes",
        replace_existing=True,
    )
    logger.info("Планировщик настроен (4 задачи)")
    return scheduler
