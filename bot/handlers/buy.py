from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from config import settings
from bot.services.marzban import marzban_service

router = Router()

@router.message(F.text == "🛒 Купить VPN")
@router.message(F.text == "/buy")
async def show_tariffs(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥉 1 Месяц - 150 ₽",   callback_data="buy_1_150")],
        [InlineKeyboardButton(text="🥈 3 Месяца - 400 ₽",  callback_data="buy_3_400")],
        [InlineKeyboardButton(text="🥇 6 Месяцев - 750 ₽", callback_data="buy_6_750")],
    ])
    await message.answer("Выберите тариф для подключения:", reply_markup=kb)


@router.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
    _, months, price = call.data.split("_")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить через Сбербанк", url=settings.sber_link)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{months}_{price}")],
    ])

    text = (
        f"Тариф: **{months} мес.**\n"
        f"К оплате: **{price} ₽**\n\n"
        f"1️⃣ Нажмите кнопку оплаты ниже.\n"
        f"2️⃣ Переведите ровно {price} ₽.\n"
        f"3️⃣ Обязательно нажмите «✅ Я оплатил!» после перевода."
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("paid_"))
async def process_paid(call: CallbackQuery, bot: Bot):
    _, months, price = call.data.split("_")
    user = call.from_user

    await call.message.edit_text(
        "⏳ Ваш запрос отправлен администратору.\n"
        "Мы проверяем поступление средств. Обычно это занимает пару минут..."
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать VPN", callback_data=f"approve_{user.id}_{months}")],
        [InlineKeyboardButton(text="❌ Не пришло",  callback_data=f"reject_{user.id}")],
    ])

    admin_text = (
        f"💰 **Новая заявка!**\n\n"
        f"👤 @{user.username} (ID: `{user.id}`)\n"
        f"📅 Тариф: {months} мес.\n"
        f"💵 {price} ₽\n\n"
        f"Если деньги пришли, жми «Выдать VPN»."
    )

    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=admin_kb,
                parse_mode="Markdown",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery, bot: Bot):
    await call.answer("Генерирую ссылку в Marzban...", show_alert=False)

    _, target_user_id, months = call.data.split("_")

    sub_link = await marzban_service.create_or_get_user(telegram_id=int(target_user_id))

    client_msg = (
        f"🎉 **Ваша подписка успешно активирована!**\n\n"
        f"🔗 **Ваша личная ссылка:**\n`{sub_link}`\n\n"
        f"📱 Скопируйте эту ссылку и вставьте в приложение Hiddify/Happ."
    )

    await bot.send_message(chat_id=int(target_user_id), text=client_msg, parse_mode="Markdown")
    await call.message.edit_text(
        f"✅ Одобрено! Ссылка отправлена пользователю `{target_user_id}`."
    )


@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery, bot: Bot):
    target_user_id = call.data.split("_")[1]
    await bot.send_message(
        chat_id=int(target_user_id),
        text="❌ **Оплата не найдена.** Напишите в поддержку.",
        parse_mode="Markdown",
    )
    await call.message.edit_text(f"❌ Заявка от юзера `{target_user_id}` отклонена.")
