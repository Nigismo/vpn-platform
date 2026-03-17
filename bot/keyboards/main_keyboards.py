"""
bot/keyboards/main_keyboards.py — Клавиатуры Telegram бота.
Все инлайн- и reply-кнопки платформы.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import settings


# ----------------------------------------------------------
# Reply-клавиатура — главное меню
# ----------------------------------------------------------
def get_main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню бота (Reply-кнопки)."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🔑 Мой VPN"),
        KeyboardButton(text="💳 Купить подписку"),
    )
    builder.row(
        KeyboardButton(text="👥 Реферальная программа"),
        KeyboardButton(text="👤 Профиль"),
    )
    builder.row(
        KeyboardButton(text="❓ Помощь"),
        KeyboardButton(text="📞 Поддержка"),
    )
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Выберите действие...",
    )


# ----------------------------------------------------------
# Инлайн-клавиатура — выбор тарифа
# ----------------------------------------------------------
def get_tariffs_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора тарифного плана."""
    builder = InlineKeyboardBuilder()

    for key, tariff in settings.tariffs.items():
        label = f"✅ {tariff['name']} — {tariff['price']}₽"
        builder.button(text=label, callback_data=f"tariff:{key}")

    builder.adjust(1)  # По одной кнопке в ряд
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back:main"))
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — выбор метода оплаты
# ----------------------------------------------------------
def get_payment_method_kb(tariff_key: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты."""
    builder = InlineKeyboardBuilder()

    if settings.yookassa_shop_id:
        builder.button(
            text="💳 Банковская карта (YooKassa)",
            callback_data=f"pay:yookassa:{tariff_key}",
        )

    if settings.sbp_phone:
        builder.button(
            text="📱 СБП (Система быстрых платежей)",
            callback_data=f"pay:sbp:{tariff_key}",
        )

    builder.button(
        text="⭐ Telegram Stars",
        callback_data=f"pay:stars:{tariff_key}",
    )

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back:tariffs"))
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — проверка оплаты YooKassa
# ----------------------------------------------------------
def get_payment_check_kb(payment_id: str) -> InlineKeyboardMarkup:
    """Кнопка проверки статуса платежа."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Проверить оплату",
        callback_data=f"check_payment:{payment_id}",
    )
    builder.button(
        text="❌ Отменить",
        callback_data="cancel_payment",
    )
    builder.adjust(1)
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — подтверждение СБП оплаты
# ----------------------------------------------------------
def get_sbp_confirm_kb(tariff_key: str, comment: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения ручной оплаты через СБП."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Я оплатил",
        callback_data=f"sbp_paid:{tariff_key}:{comment}",
    )
    builder.button(
        text="❌ Отменить",
        callback_data="cancel_payment",
    )
    builder.adjust(1)
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — раздел «Мой VPN»
# ----------------------------------------------------------
def get_myvpn_kb(has_subscription: bool = True) -> InlineKeyboardMarkup:
    """Кнопки управления VPN-подпиской."""
    builder = InlineKeyboardBuilder()

    if has_subscription:
        builder.button(text="📋 Инструкция по подключению", callback_data="vpn:instructions")
        builder.button(text="🔗 Получить ссылку подписки", callback_data="vpn:get_link")
        builder.button(text="🔄 Продлить подписку", callback_data="vpn:renew")
        builder.button(text="🌍 Сменить сервер", callback_data="vpn:change_server")
        builder.adjust(1)
    else:
        builder.button(text="💳 Купить подписку", callback_data="go:buy")
        builder.adjust(1)

    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — инструкции по платформам
# ----------------------------------------------------------
def get_platform_kb() -> InlineKeyboardMarkup:
    """Выбор платформы для инструкции по подключению."""
    builder = InlineKeyboardBuilder()
    platforms = [
        ("📱 Android", "instr:android"),
        ("🍎 iOS / iPhone", "instr:ios"),
        ("🪟 Windows", "instr:windows"),
        ("🍏 macOS", "instr:macos"),
        ("🐧 Linux", "instr:linux"),
        ("📺 TV / Router", "instr:tv"),
    ]
    for label, cb in platforms:
        builder.button(text=label, callback_data=cb)

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back:myvpn"))
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — профиль пользователя
# ----------------------------------------------------------
def get_profile_kb() -> InlineKeyboardMarkup:
    """Кнопки в разделе профиля."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 История платежей", callback_data="profile:payments")
    builder.button(text="👥 Мои рефералы", callback_data="profile:referrals")
    builder.button(text="🔗 Моя реферальная ссылка", callback_data="profile:reflink")
    builder.adjust(1)
    return builder.as_markup()


# ----------------------------------------------------------
# Инлайн-клавиатура — админ-панель
# ----------------------------------------------------------
def get_admin_kb() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    builder = InlineKeyboardBuilder()
    buttons = [
        ("📊 Статистика", "admin:stats"),
        ("🖥️ Статус нод", "admin:nodes"),
        ("👤 Найти пользователя", "admin:find_user"),
        ("📣 Рассылка", "admin:broadcast"),
        ("💰 Платежи", "admin:payments"),
        ("➕ Добавить дни", "admin:add_days"),
        ("🚫 Заблокировать", "admin:block_user"),
        ("🔓 Разблокировать", "admin:unblock_user"),
        ("✅ Активировать подписку", "admin:activate_sub"),
    ]
    for label, cb in buttons:
        builder.button(text=label, callback_data=cb)

    builder.adjust(2)
    return builder.as_markup()


# ----------------------------------------------------------
# Вспомогательные клавиатуры
# ----------------------------------------------------------
def get_back_kb(callback: str = "back:main") -> InlineKeyboardMarkup:
    """Универсальная кнопка «Назад»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=callback)
    return builder.as_markup()


def get_support_kb() -> InlineKeyboardMarkup:
    """Кнопка обращения в поддержку."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Написать в поддержку", url="https://t.me/your_support_bot")
    builder.button(text="📚 FAQ", callback_data="help:faq")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_kb(action: str) -> InlineKeyboardMarkup:
    """Универсальный запрос подтверждения действия."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"confirm:{action}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()
