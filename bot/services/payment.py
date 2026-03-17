"""
bot/services/payment.py — Сервис обработки платежей.
Интегрирует YooKassa и СБП для оплаты подписок.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from loguru import logger
from yookassa import Configuration, Payment as YKPayment
from yookassa.domain.models import Currency

from config import settings
from database.models import PaymentProvider


class PaymentService:
    """
    Сервис для создания и проверки платежей.
    Поддерживает YooKassa и СБП.
    """

    def __init__(self) -> None:
        # Настраиваем YooKassa SDK
        if settings.yookassa_shop_id and settings.yookassa_secret_key:
            Configuration.account_id = settings.yookassa_shop_id
            Configuration.secret_key = settings.yookassa_secret_key
            logger.info("✅ YooKassa настроена")
        else:
            logger.warning("⚠️ YooKassa не настроена — отсутствуют credentials")

    async def create_yookassa_payment(
        self,
        amount: float,
        description: str,
        user_id: int,
        tariff_key: str,
        return_url: Optional[str] = None,
    ) -> dict:
        """
        Создаём платёж в YooKassa.
        Возвращает словарь с payment_id и payment_url.
        """
        idempotency_key = str(uuid.uuid4())
        metadata = {
            "user_id": str(user_id),
            "tariff_key": tariff_key,
        }

        try:
            payment = YKPayment.create(
                {
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": Currency.RUB,
                    },
                    "confirmation": {
                        "type": "redirect",
                        "return_url": return_url or settings.yookassa_return_url,
                    },
                    "capture": True,
                    "description": description,
                    "metadata": metadata,
                },
                idempotency_key,
            )

            logger.info(
                f"💳 Создан платёж YooKassa: {payment.id} "
                f"на {amount}₽ для user_id={user_id}"
            )

            return {
                "payment_id": payment.id,
                "payment_url": payment.confirmation.confirmation_url,
                "provider": PaymentProvider.YOOKASSA,
                "status": payment.status,
            }

        except Exception as exc:
            logger.error(f"❌ Ошибка создания платежа YooKassa: {exc}")
            raise

    async def check_yookassa_payment(self, payment_id: str) -> dict:
        """
        Проверяем статус платежа в YooKassa.
        Возвращает словарь с актуальным статусом.
        """
        try:
            payment = YKPayment.find_one(payment_id)

            return {
                "payment_id": payment.id,
                "status": payment.status,  # "pending", "waiting_for_capture", "succeeded", "canceled"
                "amount": float(payment.amount.value),
                "paid": payment.paid,
                "metadata": payment.metadata,
            }

        except Exception as exc:
            logger.error(f"❌ Ошибка проверки платежа YooKassa {payment_id}: {exc}")
            raise

    def generate_sbp_payment_info(
        self,
        amount: float,
        user_id: int,
        tariff_key: str,
    ) -> dict:
        """
        Генерируем инструкцию для ручной оплаты через СБП.
        Возвращает данные для отображения в боте.
        """
        # Уникальный комментарий для идентификации платежа
        comment = f"VPN-{user_id}-{tariff_key.upper()}"

        return {
            "phone": settings.sbp_phone,
            "bank_name": settings.sbp_bank_name,
            "amount": amount,
            "comment": comment,
            "instructions": (
                f"📲 Переведите <b>{amount:.0f}₽</b> через СБП:\n\n"
                f"📞 Номер: <code>{settings.sbp_phone}</code>\n"
                f"🏦 Банк: {settings.sbp_bank_name}\n"
                f"💬 Комментарий: <code>{comment}</code>\n\n"
                f"⚠️ <b>Обязательно</b> укажите комментарий!\n"
                f"После оплаты нажмите кнопку «Я оплатил»"
            ),
        }

    async def verify_webhook(self, payload: dict) -> Optional[dict]:
        """
        Верифицируем вебхук от YooKassa.
        Возвращает данные платежа если всё корректно.
        """
        try:
            event_type = payload.get("event")
            payment_data = payload.get("object", {})

            if event_type not in [
                "payment.succeeded",
                "payment.canceled",
                "refund.succeeded",
            ]:
                return None

            return {
                "event": event_type,
                "payment_id": payment_data.get("id"),
                "status": payment_data.get("status"),
                "amount": float(payment_data.get("amount", {}).get("value", 0)),
                "metadata": payment_data.get("metadata", {}),
            }

        except Exception as exc:
            logger.error(f"❌ Ошибка верификации вебхука: {exc}")
            return None


# Глобальный экземпляр сервиса платежей
payment_service = PaymentService()
