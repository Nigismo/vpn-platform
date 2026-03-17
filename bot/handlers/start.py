"""
bot/handlers/start.py — Обработчики команд /start и /profile.
Регистрация пользователей и отображение профиля.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_keyboards import get_main_menu_kb, get_profile_kb
from bot.services.subscription import subscription_service
from bot.services.user_service import user_service
from config import settings

router = Router(name="start")


# ----------------------------------------------------------
# Команда /start
# ----------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    """
    Обрабатываем /start.
    Регистрируем нового пользователя, обрабатываем реферальную ссылку.
    """
    # Извлекаем реферальный код из deep link: /start REF_CODE
    referral_code = None
    if message.text and len(message.text.split()) > 1:
        referral_code = message.text.split()[1]

    user, is_new = await user_service.get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        username=message.from_user.username,
        language_code=message.from_user.language_code,
        referral_code=referral_code,
    )

    # Приветственное сообщение для нового пользователя
    if is_new:
        welcome_text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            f"🚀 <b>Добро пожаловать в наш VPN-сервис!</b>\n\n"
            f"Мы обеспечиваем:\n"
            f"🔒 Полный обход блокировок\n"
            f"⚡ Скорость до 10 Гбит/с\n"
            f"📺 4K стриминг без лагов\n"
            f"🌍 Серверы в 5+ странах\n"
            f"📱 До 3 устройств одновременно\n\n"
            f"👥 Уже <b>15 000+ пользователей</b> доверяют нам!\n\n"
            f"Выберите действие в меню ниже 👇"
        )
        if referral_code:
            welcome_text += f"\n\n🎁 Вы пришли по реферальной ссылке!"
    else:
        welcome_text = (
            f"👋 С возвращением, <b>{message.from_user.first_name}</b>!\n\n"
            f"Выберите действие в меню ниже 👇"
        )

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu_kb(),
        parse_mode="HTML",
    )


# ----------------------------------------------------------
# Команда /profile и кнопка «Профиль»
# ----------------------------------------------------------
@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message, session: AsyncSession) -> None:
    """Отображаем профиль пользователя с информацией о подписке."""
    user = await user_service.get_user(session, message.from_user.id)
    if not user:
        await message.answer("❌ Пользователь не найден. Введите /start")
        return

    # Получаем активную подписку
    subscription = await subscription_service.get_active_subscription(
        session, message.from_user.id
    )

    # Форматируем статус подписки
    if subscription:
        sub_status = subscription_service.format_subscription_info(subscription)
        sub_info = f"📡 Подписка: {sub_status}"
    else:
        sub_info = "❌ Подписка: не активна"

    # Получаем реферальную статистику
    ref_stats = await user_service.get_referral_stats(session, user.id)

    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Имя: {user.first_name}"
        f"{(' ' + user.last_name) if user.last_name else ''}\n"
        f"{'📛 Username: @' + user.username + chr(10) if user.username else ''}"
        f"\n{sub_info}\n\n"
        f"👥 Приглашено: {ref_stats['total_invited']} чел.\n"
        f"🎁 Бонусных дней получено: {ref_stats['total_bonus_days']}\n\n"
        f"🔗 Ваш реферальный код: <code>{user.referral_code}</code>"
    )

    await message.answer(
        profile_text,
        reply_markup=get_profile_kb(),
        parse_mode="HTML",
    )


# ----------------------------------------------------------
# Колбэк — реферальная ссылка
# ----------------------------------------------------------
@router.callback_query(F.data == "profile:reflink")
async def cb_referral_link(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отправляем реферальную ссылку пользователя."""
    user = await user_service.get_user(session, callback.from_user.id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.referral_code}"

    text = (
        f"🔗 <b>Ваша реферальная ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"За каждого друга, купившего подписку, вы получаете "
        f"<b>+{settings.referral_bonus_days} дней</b> к своей подписке!\n\n"
        f"Поделитесь ссылкой и зарабатывайте бесплатные месяцы 🎁"
    )

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ----------------------------------------------------------
# Команда /help и кнопка «Помощь»
# ----------------------------------------------------------
@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
    """Отображаем справочную информацию."""
    from bot.keyboards.main_keyboards import get_support_kb

    help_text = (
        f"❓ <b>Часто задаваемые вопросы</b>\n\n"
        f"<b>Как подключиться?</b>\n"
        f"Перейдите в «🔑 Мой VPN» → «Инструкция по подключению» "
        f"и выберите своё устройство.\n\n"
        f"<b>Сколько устройств можно использовать?</b>\n"
        f"До {settings.vpn_ip_limit} устройств одновременно.\n\n"
        f"<b>Можно ли сменить сервер?</b>\n"
        f"Да! В разделе «🔑 Мой VPN» нажмите «Сменить сервер».\n\n"
        f"<b>Как получить бонусные дни?</b>\n"
        f"Пригласите друга — и получите +{settings.referral_bonus_days} дней бесплатно!\n\n"
        f"<b>Вопросы и проблемы?</b>\n"
        f"Нажмите кнопку ниже и напишите в поддержку 👇"
    )

    await message.answer(
        help_text,
        reply_markup=get_support_kb(),
        parse_mode="HTML",
    )


# ----------------------------------------------------------
# Обработчик кнопки «Назад в главное меню»
# ----------------------------------------------------------
@router.callback_query(F.data == "back:main")
async def cb_back_to_main(callback: CallbackQuery) -> None:
    """Возвращаемся в главное меню."""
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню 👇",
        reply_markup=get_main_menu_kb(),
    )
    await callback.answer()
