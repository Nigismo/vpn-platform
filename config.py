"""
config.py — Центральная конфигурация платформы.
Использует pydantic-settings для валидации переменных окружения.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Основные настройки приложения, загружаемые из .env файла."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----------------------------------------------------------
    # Telegram Bot
    # ----------------------------------------------------------
    bot_token: str
    admin_ids: List[int] = []

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | List[int]) -> List[int]:
        """Парсим строку с ID администраторов через запятую."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    # ----------------------------------------------------------
    # PostgreSQL
    # ----------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vpnplatform"
    postgres_user: str = "vpnuser"
    postgres_password: str

    @property
    def database_url(self) -> str:
        """Асинхронный DSN для asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Синхронный DSN для Alembic миграций."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ----------------------------------------------------------
    # Redis
    # ----------------------------------------------------------
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        """URL подключения к Redis."""
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ----------------------------------------------------------
    # Marzban VPN Panel
    # ----------------------------------------------------------
    marzban_url: str
    marzban_username: str
    marzban_password: str

    # ----------------------------------------------------------
    # Домены (ротация анти-блок)
    # ----------------------------------------------------------
    vpn_domains: List[str] = []
    primary_domain: str = ""

    @field_validator("vpn_domains", mode="before")
    @classmethod
    def parse_vpn_domains(cls, v: str | List[str]) -> List[str]:
        """Парсим строку с доменами через запятую."""
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()]
        return v

    # ----------------------------------------------------------
    # YooKassa
    # ----------------------------------------------------------
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = "https://t.me/your_bot"

    # ----------------------------------------------------------
    # СБП / резервная оплата
    # ----------------------------------------------------------
    sbp_phone: str = ""
    sbp_bank_name: str = "Сбербанк"

    # ----------------------------------------------------------
    # Тарифы (рубли)
    # ----------------------------------------------------------
    price_1_month: int = 100
    price_3_months: int = 290
    price_6_months: int = 590
    price_12_months: int = 1200

    @property
    def tariffs(self) -> dict[str, dict]:
        """Словарь тарифов для удобного использования в коде."""
        return {
            "1m": {"name": "1 месяц", "days": 30, "price": self.price_1_month},
            "3m": {"name": "3 месяца", "days": 90, "price": self.price_3_months},
            "6m": {"name": "6 месяцев", "days": 180, "price": self.price_6_months},
            "12m": {"name": "12 месяцев", "days": 365, "price": self.price_12_months},
        }

    # ----------------------------------------------------------
    # Реферальная система
    # ----------------------------------------------------------
    referral_bonus_days: int = 30

    # ----------------------------------------------------------
    # VPN настройки пользователей
    # ----------------------------------------------------------
    vpn_ip_limit: int = 3
    vpn_default_traffic_gb: int = 0  # 0 = безлимит

    # ----------------------------------------------------------
    # Балансировка нод
    # ----------------------------------------------------------
    node_near_capacity_threshold: int = 80
    node_full_threshold: int = 95

    # ----------------------------------------------------------
    # Rate Limiting
    # ----------------------------------------------------------
    rate_limit_messages: int = 30
    rate_limit_window: int = 60

    # ----------------------------------------------------------
    # Уведомления об истечении подписки
    # ----------------------------------------------------------
    notify_days_before: List[int] = [3, 1]

    @field_validator("notify_days_before", mode="before")
    @classmethod
    def parse_notify_days(cls, v: str | List[int]) -> List[int]:
        """Парсим строку с днями уведомлений."""
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    # ----------------------------------------------------------
    # Мониторинг
    # ----------------------------------------------------------
    node_alert_threshold: int = 80

    # ----------------------------------------------------------
    # Общие настройки
    # ----------------------------------------------------------
    environment: str = "production"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        """Проверяем, работаем ли в продакшен-окружении."""
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Возвращает кешированный экземпляр настроек.
    Используем lru_cache чтобы не перечитывать .env каждый раз.
    """
    return Settings()


# Глобальный экземпляр настроек для импорта во всём проекте
settings = get_settings()
