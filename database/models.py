"""
database/models.py — Модели базы данных.
Все таблицы платформы описаны здесь через SQLAlchemy ORM.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ----------------------------------------------------------
# Базовый класс для всех моделей
# ----------------------------------------------------------
class Base(DeclarativeBase):
    """Базовый класс ORM с общими полями."""
    pass


# ----------------------------------------------------------
# Перечисления статусов
# ----------------------------------------------------------
class SubscriptionStatus(str, Enum):
    """Статусы подписки."""
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    PENDING = "pending"


class PaymentStatus(str, Enum):
    """Статусы платежа."""
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentProvider(str, Enum):
    """Провайдеры платежей."""
    YOOKASSA = "yookassa"
    SBP = "sbp"
    TELEGRAM_STARS = "telegram_stars"
    ADMIN = "admin"  # Ручное начисление администратором


class NodeStatus(str, Enum):
    """Статусы VPN-ноды."""
    ACTIVE = "active"
    NEAR_CAPACITY = "near_capacity"
    FULL = "full"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


# ----------------------------------------------------------
# Таблица: users
# ----------------------------------------------------------
class User(Base):
    """Пользователи Telegram бота."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Реферальный код этого пользователя
    referral_code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, index=True
    )
    # Через кого пришёл этот пользователь
    referred_by_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )

    # VPN логин в Marzban
    vpn_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)

    # Флаги
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Связи
    subscriptions: Mapped[List["Subscription"]] = relationship(
        back_populates="user", lazy="select", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship(
        back_populates="user", lazy="select"
    )
    referrals_sent: Mapped[List["Referral"]] = relationship(
        foreign_keys="Referral.referrer_id", back_populates="referrer"
    )
    admin_logs: Mapped[List["AdminLog"]] = relationship(
        foreign_keys="AdminLog.target_user_id", back_populates="target_user"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username}>"


# ----------------------------------------------------------
# Таблица: subscriptions
# ----------------------------------------------------------
class Subscription(Base):
    """Подписки пользователей на VPN."""
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)

    # Параметры подписки
    tariff_key: Mapped[str] = mapped_column(String(16))  # "1m", "3m", "6m", "12m"
    duration_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=SubscriptionStatus.PENDING)

    # Временные рамки
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # VPN данные
    vpn_node_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vpn_nodes.id"), nullable=True)
    subscription_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Флаги уведомлений (чтобы не слать повторно)
    notified_3_days: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_1_day: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    vpn_node: Mapped[Optional["VpnNode"]] = relationship(back_populates="subscriptions")
    payment: Mapped[Optional["Payment"]] = relationship(back_populates="subscription")

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} user_id={self.user_id} status={self.status}>"


# ----------------------------------------------------------
# Таблица: payments
# ----------------------------------------------------------
class Payment(Base):
    """Платежи за подписку."""
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
    )

    # Параметры платежа
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    provider: Mapped[str] = mapped_column(String(32))  # PaymentProvider
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING, index=True)

    # Внешний ID платежа от провайдера
    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)
    # Ссылка на оплату
    payment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Метаданные
    meta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON строка

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Связи
    user: Mapped["User"] = relationship(back_populates="payments")
    subscription: Mapped[Optional["Subscription"]] = relationship(back_populates="payment")

    def __repr__(self) -> str:
        return f"<Payment id={self.id} amount={self.amount} status={self.status}>"


# ----------------------------------------------------------
# Таблица: referrals
# ----------------------------------------------------------
class Referral(Base):
    """Реферальные связи между пользователями."""
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    referred_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, unique=True)

    # Вознаграждение начислено?
    bonus_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    bonus_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связи
    referrer: Mapped["User"] = relationship(foreign_keys=[referrer_id], back_populates="referrals_sent")

    def __repr__(self) -> str:
        return f"<Referral referrer={self.referrer_id} referred={self.referred_id}>"


# ----------------------------------------------------------
# Таблица: vpn_nodes
# ----------------------------------------------------------
class VpnNode(Base):
    """VPN-ноды (серверы Marzban)."""
    __tablename__ = "vpn_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[str] = mapped_column(String(64))  # "NL", "DE", "FI" и т.д.
    country_emoji: Mapped[str] = mapped_column(String(8), default="🌍")
    ip_address: Mapped[str] = mapped_column(String(64))

    # Ссылка на панель Marzban этой ноды
    marzban_url: Mapped[str] = mapped_column(String(256))
    marzban_username: Mapped[str] = mapped_column(String(128))
    marzban_password: Mapped[str] = mapped_column(String(256))  # Зашифрованный пароль

    # Загрузка
    current_users: Mapped[int] = mapped_column(Integer, default=0)
    max_users: Mapped[int] = mapped_column(Integer, default=500)
    status: Mapped[str] = mapped_column(String(32), default=NodeStatus.ACTIVE, index=True)

    # Протоколы для DPI-обхода
    supports_reality: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_grpc: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_hysteria2: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_ws_cdn: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="vpn_node")

    @property
    def load_percent(self) -> float:
        """Процент загрузки ноды."""
        if self.max_users == 0:
            return 100.0
        return round((self.current_users / self.max_users) * 100, 1)

    def __repr__(self) -> str:
        return f"<VpnNode id={self.id} country={self.country} load={self.load_percent}%>"


# ----------------------------------------------------------
# Таблица: vpn_domains
# ----------------------------------------------------------
class VpnDomain(Base):
    """Домены для подписочных ссылок (ротация для анти-блок)."""
    __tablename__ = "vpn_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # Выше = приоритетнее

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<VpnDomain domain={self.domain} active={self.is_active}>"


# ----------------------------------------------------------
# Таблица: admin_logs
# ----------------------------------------------------------
class AdminLog(Base):
    """Журнал действий администраторов."""
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Telegram ID адм.
    target_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(128))  # "block_user", "add_days", etc.
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связи
    target_user: Mapped[Optional["User"]] = relationship(
        foreign_keys=[target_user_id], back_populates="admin_logs"
    )

    def __repr__(self) -> str:
        return f"<AdminLog admin={self.admin_id} action={self.action}>"
