"""
bot/handlers/admin.py — Обработчики административной панели.
Статистика, управление пользователями, рассылки, управление нодами.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_keyboards import get_admin_kb, get_back_kb
from bot.services.node_balancer import node_balancer
from bot.services.subscription import subscription_service
from bot.services.user_service import user_service
from config import settings
from database.models import (
    AdminLog,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
    User,
)

router = Router(name="admin")


class AdminStates(StatesGroup):
    """Состояния FSM для административных операций."""
    waiting_for_broadcast_message = State()
    waiting_for_user_id = State()
    waiting_for_days_and_user = State()
    waiting_for_activate_info = State()


def is_admin(user_id: int) -> bool:
    """Проверяем, является ли пользователь администратором."""
    return user_id in settings.admin_ids


def admin_only(func):
    """Декоратор для ограничения доступа только администраторам."""
    import functools

    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        user_id = (
            event.from_user.id
            if hasattr(event, "from_user")
            else None
        )
        if not user_id or not is_admin(user_id):
            if hasattr(event, "answer"):
                await event.answer("🚫 Доступ запрещён")
            return
        return await func(event, *args, **kwargs)

    return wrapper


# ----------------------------------------------------------
# Команда /admin — главная панель
# ----------------------------------------------------------
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Открываем административную панель."""
    if not is_admin(message.from_user.id):
        await message.answer("🚫 Доступ запрещён")
        return

    await message.answer(
        "🛠 <b>Административная панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_kb(),
        parse_mode="HTML",
    )


# ----------------------------------------------------------
# Колбэк — статистика платформы
# ----------------------------------------------------------
@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отображаем общую статистику платформы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    # Общее число пользователей
    total_users = await session.execute(select(func.count(User.id)))
    # Активных подписок
    active_subs = await session.execute(
        select(func.count(Subscription.id)).where(
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    # Выручка сегодня
    from datetime import timedelta
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    revenue_today = await session.execute(
        select(func.sum(Payment.amount)).where(
            Payment.status == PaymentStatus.SUCCEEDED,
            Payment.paid_at >= today_start,
        )
    )
    # Выручка за месяц
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)
    revenue_month = await session.execute(
        select(func.sum(Payment.amount)).where(
            Payment.status == PaymentStatus.SUCCEEDED,
            Payment.paid_at >= month_start,
        )
    )
    # Новых пользователей сегодня
    new_today = await session.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )

    # Статус нод
    nodes_stats = await node_balancer.get_all_nodes_stats(session)
    nodes_summary = "\n".join([
        f"  {n['emoji']} {n['country']}: {n['current_users']}/{n['max_users']} "
        f"({n['load_percent']}%) [{n['status']}]"
        for n in nodes_stats
    ]) or "  Нет нод"

    text = (
        f"📊 <b>Статистика платформы</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users.scalar() or 0}</b>\n"
        f"✅ Активных подписок: <b>{active_subs.scalar() or 0}</b>\n"
        f"🆕 Новых сегодня: <b>{new_today.scalar() or 0}</b>\n\n"
        f"💰 Выручка сегодня: <b>{revenue_today.scalar() or 0:.0f}₽</b>\n"
        f"💰 Выручка за месяц: <b>{revenue_month.scalar() or 0:.0f}₽</b>\n\n"
        f"🖥️ <b>Статус нод:</b>\n{nodes_summary}\n\n"
        f"🕐 Обновлено: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("back:admin"),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — статус нод
# ----------------------------------------------------------
@router.callback_query(F.data == "admin:nodes")
async def cb_admin_nodes(callback: CallbackQuery, session: AsyncSession) -> None:
    """Детальная статистика по всем VPN-нодам."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    nodes_stats = await node_balancer.get_all_nodes_stats(session)

    if not nodes_stats:
        text = "🖥️ <b>Ноды не настроены</b>"
    else:
        text = "🖥️ <b>Статус VPN-нод</b>\n\n"
        for node in nodes_stats:
            # Прогресс-бар загрузки
            filled = int(node["load_percent"] / 10)
            bar = "█" * filled + "░" * (10 - filled)
            status_emoji = {"active": "🟢", "near_capacity": "🟡", "full": "🔴", "offline": "⚫"}.get(
                node["status"], "⚪"
            )

            text += (
                f"{status_emoji} {node['emoji']} <b>{node['country']}</b> — {node['name']}\n"
                f"   IP: <code>{node['ip']}</code>\n"
                f"   [{bar}] {node['load_percent']}%\n"
                f"   Пользователи: {node['current_users']}/{node['max_users']}\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("back:admin"),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — начать рассылку
# ----------------------------------------------------------
@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем текст для массовой рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.edit_text(
        "📣 <b>Рассылка</b>\n\n"
        "Введите текст сообщения для рассылки всем пользователям.\n"
        "Поддерживается HTML-форматирование.\n\n"
        "Для отмены введите /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Выполняем рассылку всем пользователям."""
    if not is_admin(message.from_user.id):
        return

    broadcast_text = message.text or message.caption or ""

    if broadcast_text.startswith("/cancel"):
        await state.clear()
        await message.answer("❌ Рассылка отменена")
        return

    await state.clear()

    # Получаем всех активных пользователей
    result = await session.execute(
        select(User.id).where(User.is_blocked == False)
    )
    user_ids = [row[0] for row in result.fetchall()]

    await message.answer(
        f"📣 Начинаем рассылку для {len(user_ids)} пользователей..."
    )

    # Рассылка с задержкой (избегаем flood limit)
    sent = 0
    failed = 0

    import asyncio
    for user_id in user_ids:
        try:
            await message.bot.send_message(
                user_id,
                broadcast_text,
                parse_mode="HTML",
            )
            sent += 1
            # Задержка для соблюдения лимитов Telegram API
            if sent % 30 == 0:
                await asyncio.sleep(1)
        except Exception:
            failed += 1

    # Логируем действие
    session.add(AdminLog(
        admin_id=message.from_user.id,
        action="broadcast",
        details=f"Отправлено: {sent}, Ошибок: {failed}",
    ))

    await message.answer(
        f"✅ Рассылка завершена!\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}"
    )


# ----------------------------------------------------------
# Колбэк — добавить дни пользователю
# ----------------------------------------------------------
@router.callback_query(F.data == "admin:add_days")
async def cb_admin_add_days(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем данные для добавления бонусных дней."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_days_and_user)
    await callback.message.edit_text(
        "➕ <b>Добавить дни</b>\n\n"
        "Введите в формате:\n"
        "<code>USER_ID DAYS</code>\n\n"
        "Пример: <code>123456789 30</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_days_and_user)
async def process_add_days(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Добавляем бонусные дни к подписке пользователя."""
    if not is_admin(message.from_user.id):
        return

    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.answer("❌ Неверный формат. Введите: USER_ID DAYS")
            return

        target_user_id = int(parts[0])
        days = int(parts[1])

        await state.clear()

        success = await subscription_service.add_bonus_days(
            session, target_user_id, days,
            reason=f"Ручное начисление от admin={message.from_user.id}"
        )

        if success:
            # Уведомляем пользователя
            try:
                await message.bot.send_message(
                    target_user_id,
                    f"🎁 Администратор добавил вам <b>{days} дней</b> к подписке!",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            # Логируем действие
            session.add(AdminLog(
                admin_id=message.from_user.id,
                target_user_id=target_user_id,
                action="add_days",
                details=f"+{days} дней",
            ))

            await message.answer(f"✅ Добавлено {days} дней для пользователя {target_user_id}")
        else:
            await message.answer("❌ Не удалось добавить дни. Нет активной подписки.")

    except ValueError:
        await message.answer("❌ Неверный формат. Введите: USER_ID DAYS")


# ----------------------------------------------------------
# Колбэк — заблокировать / разблокировать пользователя
# ----------------------------------------------------------
@router.callback_query(F.data.in_(["admin:block_user", "admin:unblock_user"]))
async def cb_admin_block_user(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем ID пользователя для блокировки/разблокировки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    action = "block" if "block_user" in callback.data else "unblock"
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(admin_action=action)

    action_text = "заблокировать" if action == "block" else "разблокировать"
    await callback.message.edit_text(
        f"🚫 <b>{'Блокировка' if action == 'block' else 'Разблокировка'} пользователя</b>\n\n"
        f"Введите Telegram ID пользователя, которого нужно {action_text}:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_user_id)
async def process_user_id(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Обрабатываем ID пользователя для административного действия."""
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    action = data.get("admin_action", "block")

    try:
        target_user_id = int(message.text.strip())
        await state.clear()

        blocked = action == "block"
        success = await user_service.block_user(session, target_user_id, blocked)

        if success:
            action_text = "заблокирован" if blocked else "разблокирован"

            # Логируем действие
            session.add(AdminLog(
                admin_id=message.from_user.id,
                target_user_id=target_user_id,
                action=f"{'block' if blocked else 'unblock'}_user",
            ))

            await message.answer(
                f"✅ Пользователь {target_user_id} {action_text}"
            )
        else:
            await message.answer("❌ Пользователь не найден")

    except ValueError:
        await message.answer("❌ Неверный ID. Введите числовой Telegram ID")


# ----------------------------------------------------------
# Колбэк — активировать подписку вручную (для СБП)
# ----------------------------------------------------------
@router.callback_query(F.data == "admin:activate_sub")
async def cb_admin_activate_sub(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем данные для ручной активации подписки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_activate_info)
    await callback.message.edit_text(
        "✅ <b>Активация подписки</b>\n\n"
        "Введите в формате:\n"
        "<code>USER_ID TARIFF_KEY</code>\n\n"
        "Например: <code>123456789 3m</code>\n\n"
        "Доступные тарифы: 1m, 3m, 6m, 12m",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_activate_info)
async def process_activate_subscription(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Активируем подписку вручную для пользователя."""
    if not is_admin(message.from_user.id):
        return

    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.answer("❌ Неверный формат. Введите: USER_ID TARIFF_KEY")
            return

        target_user_id = int(parts[0])
        tariff_key = parts[1].lower()
        await state.clear()

        # Получаем пользователя
        target_user = await user_service.get_user(session, target_user_id)
        if not target_user:
            await message.answer("❌ Пользователь не найден")
            return

        # Создаём подписку
        subscription = await subscription_service.create_subscription(
            session=session,
            user=target_user,
            tariff_key=tariff_key,
        )

        # Логируем
        session.add(AdminLog(
            admin_id=message.from_user.id,
            target_user_id=target_user_id,
            action="activate_subscription",
            details=f"tariff={tariff_key}",
        ))

        # Уведомляем пользователя
        tariff = settings.tariffs.get(tariff_key, {})
        try:
            await message.bot.send_message(
                target_user_id,
                f"🎉 <b>Ваша подписка активирована!</b>\n\n"
                f"✅ Тариф: {tariff.get('name', tariff_key)}\n"
                f"📅 Действует до: {subscription.expires_at.strftime('%d.%m.%Y')}\n\n"
                f"🔗 Ссылка: <code>{subscription.subscription_url}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await message.answer(
            f"✅ Подписка ({tariff_key}) активирована для пользователя {target_user_id}"
        )

    except (ValueError, RuntimeError) as exc:
        await message.answer(f"❌ Ошибка: {exc}")


# ----------------------------------------------------------
# Навигация «Назад» в главное меню администратора
# ----------------------------------------------------------
@router.callback_query(F.data == "back:admin")
async def cb_back_to_admin(callback: CallbackQuery) -> None:
    """Возвращаемся в главное меню администратора."""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён", show_alert=True)
        return

    await callback.message.edit_text(
        "🛠 <b>Административная панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_kb(),
        parse_mode="HTML",
    )
    await callback.answer()
