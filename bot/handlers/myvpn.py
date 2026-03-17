"""
bot/handlers/myvpn.py — Обработчики раздела «Мой VPN».
Просмотр подписки, инструкции по подключению, смена сервера.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_keyboards import (
    get_back_kb,
    get_myvpn_kb,
    get_platform_kb,
    get_tariffs_kb,
)
from bot.services.subscription import subscription_service
from bot.services.user_service import user_service

router = Router(name="myvpn")


# ----------------------------------------------------------
# Команда /myvpn и кнопка «Мой VPN»
# ----------------------------------------------------------
@router.message(Command("myvpn"))
@router.message(F.text == "🔑 Мой VPN")
async def cmd_myvpn(message: Message, session: AsyncSession) -> None:
    """Показываем информацию об активной подписке пользователя."""
    subscription = await subscription_service.get_active_subscription(
        session, message.from_user.id
    )

    if subscription:
        user = await user_service.get_user(session, message.from_user.id)
        expire_info = subscription_service.format_subscription_info(subscription)

        # Получаем информацию о ноде
        node_info = ""
        if subscription.vpn_node:
            node = subscription.vpn_node
            node_info = (
                f"\n🌍 Сервер: {node.country_emoji} {node.country} ({node.name})"
            )

        text = (
            f"🔑 <b>Ваша VPN подписка</b>\n\n"
            f"📅 Статус: {expire_info}{node_info}\n\n"
            f"🔗 Ссылка подписки:\n"
            f"<code>{subscription.subscription_url}</code>\n\n"
            f"Используйте эту ссылку для настройки любого VPN-клиента.\n"
            f"Поддерживаемые клиенты: v2rayNG, Hiddify, Sing-box, Streisand"
        )

        await message.answer(
            text,
            reply_markup=get_myvpn_kb(has_subscription=True),
            parse_mode="HTML",
        )
    else:
        text = (
            f"❌ <b>У вас нет активной подписки</b>\n\n"
            f"🚀 Подключитесь к нашей VPN и получите:\n"
            f"• Полный обход блокировок\n"
            f"• Скорость до 10 Гбит/с\n"
            f"• 4K стриминг без лагов\n"
            f"• До 3 устройств одновременно\n\n"
            f"💎 Тарифы от <b>100₽/месяц</b>\n\n"
            f"👇 Нажмите кнопку для покупки:"
        )
        await message.answer(
            text,
            reply_markup=get_myvpn_kb(has_subscription=False),
            parse_mode="HTML",
        )


# ----------------------------------------------------------
# Колбэк — получить ссылку подписки
# ----------------------------------------------------------
@router.callback_query(F.data == "vpn:get_link")
async def cb_get_link(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отправляем актуальную ссылку на VPN-подписку."""
    subscription = await subscription_service.get_active_subscription(
        session, callback.from_user.id
    )

    if not subscription:
        await callback.answer("❌ Нет активной подписки", show_alert=True)
        return

    text = (
        f"🔗 <b>Ваша ссылка подписки:</b>\n\n"
        f"<code>{subscription.subscription_url}</code>\n\n"
        f"Скопируйте ссылку и добавьте её в VPN-клиент.\n\n"
        f"📱 <b>Рекомендуемые клиенты:</b>\n"
        f"• Android: v2rayNG, Hiddify Next\n"
        f"• iOS: Sing-Box, Streisand\n"
        f"• Windows: v2rayN, Hiddify\n"
        f"• macOS: Hiddify, Sing-Box"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_kb("back:myvpn"),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — инструкции по подключению (выбор платформы)
# ----------------------------------------------------------
@router.callback_query(F.data == "vpn:instructions")
async def cb_instructions(callback: CallbackQuery) -> None:
    """Показываем список платформ для инструкций."""
    text = (
        f"📋 <b>Инструкция по подключению</b>\n\n"
        f"Выберите вашу платформу:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_platform_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэки — инструкции для конкретных платформ
# ----------------------------------------------------------
PLATFORM_INSTRUCTIONS = {
    "instr:android": (
        "📱 <b>Подключение на Android</b>\n\n"
        "1️⃣ Скачайте <b>Hiddify Next</b> из Google Play или GitHub\n\n"
        "2️⃣ Откройте приложение → нажмите <b>«+»</b>\n\n"
        "3️⃣ Выберите <b>«Добавить из буфера»</b> или <b>«Ссылка на подписку»</b>\n\n"
        "4️⃣ Вставьте вашу ссылку подписки\n\n"
        "5️⃣ Нажмите <b>«Подключить»</b> ✅\n\n"
        "💡 <b>Совет:</b> Используйте режим «Auto» для автовыбора лучшего протокола"
    ),
    "instr:ios": (
        "🍎 <b>Подключение на iOS / iPhone</b>\n\n"
        "1️⃣ Скачайте <b>Sing-Box</b> из App Store\n\n"
        "2️⃣ Откройте «Настройки» → «Профили» → <b>«+»</b>\n\n"
        "3️⃣ Выберите <b>«URL подписки»</b>\n\n"
        "4️⃣ Вставьте вашу ссылку подписки\n\n"
        "5️⃣ Нажмите <b>«Обновить»</b> и включите VPN ✅\n\n"
        "💡 Разрешите добавление VPN-конфигурации при запросе"
    ),
    "instr:windows": (
        "🪟 <b>Подключение на Windows</b>\n\n"
        "1️⃣ Скачайте <b>Hiddify</b> с GitHub\n\n"
        "2️⃣ Запустите → нажмите <b>«Добавить профиль»</b>\n\n"
        "3️⃣ Выберите <b>«По ссылке»</b>\n\n"
        "4️⃣ Вставьте ссылку подписки → <b>«Добавить»</b>\n\n"
        "5️⃣ Нажмите <b>«Подключить»</b> в системном трее ✅\n\n"
        "💡 При первом запуске разрешите доступ в брандмауэре"
    ),
    "instr:macos": (
        "🍏 <b>Подключение на macOS</b>\n\n"
        "1️⃣ Скачайте <b>Hiddify</b> или <b>Sing-Box</b> из App Store\n\n"
        "2️⃣ Откройте приложение → <b>«Add Profile»</b>\n\n"
        "3️⃣ Вставьте ссылку подписки\n\n"
        "4️⃣ Нажмите <b>«Connect»</b> ✅\n\n"
        "💡 При запросе разрешите добавление VPN-профиля"
    ),
    "instr:linux": (
        "🐧 <b>Подключение на Linux</b>\n\n"
        "1️⃣ Установите <b>Hiddify</b>:\n"
        "<code>sudo snap install hiddify</code>\n\n"
        "2️⃣ Или скачайте AppImage с GitHub\n\n"
        "3️⃣ Добавьте ссылку подписки в приложении\n\n"
        "4️⃣ Подключитесь ✅\n\n"
        "💡 Также доступен CLI-клиент sing-box для серверов"
    ),
    "instr:tv": (
        "📺 <b>Подключение на TV / Роутер</b>\n\n"
        "<b>Для Android TV:</b>\n"
        "1️⃣ Скачайте v2rayNG из APKPure\n"
        "2️⃣ Добавьте ссылку подписки\n\n"
        "<b>Для роутера (OpenWRT):</b>\n"
        "1️⃣ Установите пакет sing-box\n"
        "2️⃣ Используйте конфиг из личного кабинета\n\n"
        "💡 Напишите в поддержку для помощи с настройкой роутера"
    ),
}


@router.callback_query(F.data.startswith("instr:"))
async def cb_platform_instruction(callback: CallbackQuery, session: AsyncSession) -> None:
    """Показываем инструкцию для выбранной платформы."""
    platform_key = callback.data

    instruction = PLATFORM_INSTRUCTIONS.get(platform_key)
    if not instruction:
        await callback.answer("❌ Инструкция не найдена", show_alert=True)
        return

    # Добавляем ссылку на подписку
    subscription = await subscription_service.get_active_subscription(
        session, callback.from_user.id
    )

    if subscription:
        instruction += (
            f"\n\n🔗 <b>Ваша ссылка подписки:</b>\n"
            f"<code>{subscription.subscription_url}</code>"
        )

    await callback.message.edit_text(
        instruction,
        reply_markup=get_back_kb("vpn:instructions"),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — продление подписки
# ----------------------------------------------------------
@router.callback_query(F.data == "vpn:renew")
async def cb_renew_subscription(callback: CallbackQuery) -> None:
    """Перенаправляем на страницу выбора тарифа для продления."""
    text = (
        f"🔄 <b>Продление подписки</b>\n\n"
        f"Выберите тариф для продления:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_tariffs_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — навигация «Назад» в раздел «Мой VPN»
# ----------------------------------------------------------
@router.callback_query(F.data == "back:myvpn")
async def cb_back_to_myvpn(callback: CallbackQuery, session: AsyncSession) -> None:
    """Возвращаемся к главной странице «Мой VPN»."""
    subscription = await subscription_service.get_active_subscription(
        session, callback.from_user.id
    )

    text = "🔑 <b>Мой VPN</b>\n\nВыберите действие:"
    await callback.message.edit_text(
        text,
        reply_markup=get_myvpn_kb(has_subscription=bool(subscription)),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------
# Колбэк — перейти к покупке
# ----------------------------------------------------------
@router.callback_query(F.data == "go:buy")
async def cb_go_buy(callback: CallbackQuery) -> None:
    """Перенаправляем на выбор тарифа."""
    text = (
        f"💎 <b>Выберите тарифный план</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_tariffs_kb(),
        parse_mode="HTML",
    )
    await callback.answer()
