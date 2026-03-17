"""
bot/handlers/buy.py — Обработчики процесса покупки подписки.
Выбор тарифа → выбор оплаты → создание платежа → активация VPN.
"""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_keyboards import (
    get_back_kb,
    get_payment_check_kb,
    get_payment_method_kb,
    get_sbp_confirm_kb,
    get_tariffs_kb,
)
from bot.services.payment import payment_service
from bot.services.subscription import subscription_service
from bot.services.user_service import user_service
from config import settings
from database.models import Payment, PaymentProvider, PaymentStatus
from database.session import get_session

router = Router(name="buy")


class PaymentStates(StatesGroup):
    """Состояния FSM для процесса оплаты."""
    waiting_for_sbp_confirmation = State()
    waiting_for_admin_payment = State()


# ----------------------------------------------------------
# Команда /buy и кнопка «Купить подписку»
# ----------------------------------------------------------
@router.message(Command("buy"))
@router.message(F.text == "💳 Купить подписку")
async def cmd_buy(message: Message) -> None:
    """Показываем доступные тарифы."""
    text = (
        f"💎 <b>Выберите тарифный план</b>\n\n"
        f"🚀 Быстрое соединение\n"
        f"🔒 Полный обход блокировок\n"
        f"📺 4K без лагов\n"
        f"📱 До {settings.vpn_ip_limit} устройств\n\n"
        f"<b>Доступные тарифы:</b>\n"
    )

    for key, tariff in settings.tariffs.items():
        # Рассчитываем стоимость в день
        daily = tariff["price"] / tariff["days"]
        text += f"\n{'✅'} <b>{tariff['name']}</b> — {tariff['price']}₽ (~{daily:.1f}₽/день)"

    text += "\n\n👇 Выберите подходящий план:"

    await message.answer(
        text,
        reply_markup=get_tariffs_kb(),
        parse_mode="HTML",
    )


# ----------------------------------------------------------
# Колбэк — выбор тарифа
# ----------------------------------------------------------
@router.callback_query(F.data.startswith("tariff:"))
async def cb_select_tariff(callback: CallbackQuery) -> None:
    """Пользователь выбрал тариф — показываем способы оплаты."""
    tariff_key = callback.data.split(":")[1]
    tariff = settings.tariffs.get(tariff_key)

    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    text = (
        f"✅ <b>Выбран тариф: {tariff['name']}</b>\n"
        f"💰 Сумма: <b>{tariff['price']}₽</b>\n\n"
        f"Выберите способ оплаты:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_payment_method_kb(tariff_key),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — оплата через YooKassa
# ----------------------------------------------------------
@router.callback_query(F.data.startswith("pay:yookassa:"))
async def cb_pay_yookassa(callback: CallbackQuery, session: AsyncSession) -> None:
    """Создаём платёж в YooKassa и отправляем ссылку."""
    tariff_key = callback.data.split(":")[2]
    tariff = settings.tariffs.get(tariff_key)

    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    await callback.answer("⏳ Создаём платёж...")

    try:
        payment_data = await payment_service.create_yookassa_payment(
            amount=tariff["price"],
            description=f"VPN подписка {tariff['name']}",
            user_id=callback.from_user.id,
            tariff_key=tariff_key,
        )

        # Сохраняем платёж в БД
        payment = Payment(
            user_id=callback.from_user.id,
            amount=tariff["price"],
            provider=PaymentProvider.YOOKASSA,
            status=PaymentStatus.PENDING,
            external_id=payment_data["payment_id"],
            payment_url=payment_data["payment_url"],
        )
        session.add(payment)
        await session.flush()

        text = (
            f"💳 <b>Оплата через карту</b>\n\n"
            f"Тариф: <b>{tariff['name']}</b>\n"
            f"Сумма: <b>{tariff['price']}₽</b>\n\n"
            f"👇 Нажмите кнопку для оплаты:\n"
            f'<a href="{payment_data["payment_url"]}">💳 Оплатить {tariff["price"]}₽</a>\n\n'
            f"После оплаты нажмите «Проверить оплату»"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_payment_check_kb(payment_data["payment_id"]),
            parse_mode="HTML",
        )

    except Exception as exc:
        logger.error(f"Ошибка создания платежа YooKassa: {exc}")
        await callback.message.edit_text(
            "❌ Ошибка при создании платежа. Попробуйте позже или выберите другой способ.",
            reply_markup=get_back_kb("back:tariffs"),
        )


# ----------------------------------------------------------
# Колбэк — проверка платежа YooKassa
# ----------------------------------------------------------
@router.callback_query(F.data.startswith("check_payment:"))
async def cb_check_payment(callback: CallbackQuery, session: AsyncSession) -> None:
    """Проверяем статус платежа в YooKassa и активируем подписку."""
    payment_id = callback.data.split(":")[1]

    await callback.answer("🔄 Проверяем платёж...")

    try:
        payment_info = await payment_service.check_yookassa_payment(payment_id)

        if payment_info["status"] == "succeeded" and payment_info["paid"]:
            # Платёж прошёл — активируем подписку
            metadata = payment_info["metadata"]
            tariff_key = metadata.get("tariff_key", "1m")
            user_id = int(metadata.get("user_id", callback.from_user.id))

            # Получаем пользователя
            user = await user_service.get_user(session, user_id)
            if not user:
                await callback.message.edit_text("❌ Пользователь не найден")
                return

            # Создаём подписку
            subscription = await subscription_service.create_subscription(
                session=session,
                user=user,
                tariff_key=tariff_key,
            )

            # Обновляем платёж в БД
            from sqlalchemy import select
            result = await session.execute(
                select(Payment).where(Payment.external_id == payment_id)
            )
            payment = result.scalar_one_or_none()
            if payment:
                from datetime import datetime, timezone
                payment.status = PaymentStatus.SUCCEEDED
                payment.paid_at = datetime.now(timezone.utc)
                payment.subscription_id = subscription.id

            # Обрабатываем реферальный бонус (если первая оплата)
            await user_service.process_referral_bonus(session, user_id)

            tariff = settings.tariffs.get(tariff_key, {})
            success_text = (
                f"🎉 <b>Подписка активирована!</b>\n\n"
                f"✅ Тариф: {tariff.get('name', tariff_key)}\n"
                f"📅 Действует до: {subscription.expires_at.strftime('%d.%m.%Y')}\n\n"
                f"🔗 Ссылка на подписку:\n"
                f"<code>{subscription.subscription_url}</code>\n\n"
                f"👇 Перейдите в «🔑 Мой VPN» для инструкций по подключению"
            )

            await callback.message.edit_text(success_text, parse_mode="HTML")
            logger.info(f"✅ Подписка активирована для user={user_id}, tariff={tariff_key}")

        elif payment_info["status"] == "canceled":
            await callback.message.edit_text(
                "❌ Платёж отменён. Попробуйте снова.",
                reply_markup=get_back_kb("back:tariffs"),
            )
        else:
            # Платёж ещё не прошёл
            await callback.answer(
                "⏳ Платёж ещё не поступил. Оплатите и нажмите снова.",
                show_alert=True,
            )

    except Exception as exc:
        logger.error(f"Ошибка проверки платежа {payment_id}: {exc}")
        await callback.answer(
            "❌ Ошибка проверки. Попробуйте позже.",
            show_alert=True,
        )


# ----------------------------------------------------------
# Колбэк — оплата через СБП
# ----------------------------------------------------------
@router.callback_query(F.data.startswith("pay:sbp:"))
async def cb_pay_sbp(callback: CallbackQuery, state: FSMContext) -> None:
    """Отображаем инструкцию для оплаты через СБП."""
    tariff_key = callback.data.split(":")[2]
    tariff = settings.tariffs.get(tariff_key)

    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    sbp_info = payment_service.generate_sbp_payment_info(
        amount=tariff["price"],
        user_id=callback.from_user.id,
        tariff_key=tariff_key,
    )

    await state.set_state(PaymentStates.waiting_for_sbp_confirmation)
    await state.update_data(tariff_key=tariff_key, sbp_comment=sbp_info["comment"])

    await callback.message.edit_text(
        sbp_info["instructions"],
        reply_markup=get_sbp_confirm_kb(tariff_key, sbp_info["comment"]),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — пользователь нажал «Я оплатил» (СБП)
# ----------------------------------------------------------
@router.callback_query(F.data.startswith("sbp_paid:"))
async def cb_sbp_paid(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Пользователь заявил об оплате СБП.
    Создаём ожидающий платёж и уведомляем администратора.
    """
    parts = callback.data.split(":")
    tariff_key = parts[1]
    sbp_comment = parts[2] if len(parts) > 2 else ""

    tariff = settings.tariffs.get(tariff_key)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    # Сохраняем ожидающий платёж в БД
    payment = Payment(
        user_id=callback.from_user.id,
        amount=tariff["price"],
        provider=PaymentProvider.SBP,
        status=PaymentStatus.PENDING,
        external_id=sbp_comment,
    )
    session.add(payment)
    await session.flush()

    await state.clear()

    # Уведомляем администраторов
    admin_text = (
        f"💰 <b>Новый запрос на оплату СБП</b>\n\n"
        f"👤 Пользователь: {callback.from_user.id} "
        f"(@{callback.from_user.username or 'нет'})\n"
        f"💎 Тариф: {tariff['name']}\n"
        f"💰 Сумма: {tariff['price']}₽\n"
        f"💬 Комментарий: <code>{sbp_comment}</code>\n\n"
        f"Проверьте поступление средств и активируйте подписку:\n"
        f"/admin activate {callback.from_user.id} {tariff_key}"
    )

    for admin_id in settings.admin_ids:
        try:
            await callback.bot.send_message(
                admin_id, admin_text, parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.message.edit_text(
        "⏳ <b>Заявка на проверку отправлена!</b>\n\n"
        "Мы проверим поступление средств и активируем вашу подписку "
        "в течение нескольких минут.\n\n"
        "Вы получите уведомление как только подписка будет активирована.",
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — отмена платежа
# ----------------------------------------------------------
@router.callback_query(F.data == "cancel_payment")
async def cb_cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяем процесс оплаты и возвращаем в главное меню."""
    from bot.keyboards.main_keyboards import get_main_menu_kb

    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "❌ Оплата отменена. Вернулись в главное меню.",
        reply_markup=get_main_menu_kb(),
    )
    await callback.answer()


# ----------------------------------------------------------
# Навигация «Назад» к тарифам
# ----------------------------------------------------------
@router.callback_query(F.data == "back:tariffs")
async def cb_back_to_tariffs(callback: CallbackQuery) -> None:
    """Возвращаемся к выбору тарифа."""
    text = (
        f"💎 <b>Выберите тарифный план</b>\n\n"
        f"🚀 Быстрое соединение · 🔒 Полный обход блокировок\n"
        f"📺 4K без лагов · 📱 До {settings.vpn_ip_limit} устройств\n"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_tariffs_kb(),
        parse_mode="HTML",
    )
    await callback.answer()
