"""
config.py — Центральная конфигурация платформы.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot
    bot_token: str = ""
    # Храним как строку, список получаем через property
    admin_ids: str = ""

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.admin_ids:
            return []
        try:
            return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]
        except Exception:
            return []

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vpnplatform"
    postgres_user: str = "vpnuser"
    postgres_password: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Marzban
    marzban_url: str = ""
    marzban_username: str = ""
    marzban_password: str = ""

    # VPN домены — строка, список через property
    vpn_domains: str = ""
    primary_domain: str = ""

    @property
    def vpn_domains_list(self) -> List[str]:
        if not self.vpn_domains:
            return []
        return [d.strip() for d in self.vpn_domains.split(",") if d.strip()]

    # Ссылка на оплату Сбербанк
    sber_link: str = ""

    # YooKassa
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = "https://t.me/your_bot"

    # СБП
    sbp_phone: str = ""
    sbp_bank_name: str = "Сбербанк"

    # Тарифы
    price_1_month: int = 100
    price_3_months: int = 290
    price_6_months: int = 590
    price_12_months: int = 1200

    @property
    def tariffs(self) -> dict:
        return {
            "1m":  {"name": "1 месяц",    "days": 30,  "price": self.price_1_month},
            "3m":  {"name": "3 месяца",   "days": 90,  "price": self.price_3_months},
            "6m":  {"name": "6 месяцев",  "days": 180, "price": self.price_6_months},
            "12m": {"name": "12 месяцев", "days": 365, "price": self.price_12_months},
        }

    # Реферальная система
    referral_bonus_days: int = 30

    # VPN настройки
    vpn_ip_limit: int = 3
    vpn_default_traffic_gb: int = 0

    # Балансировка нод
    node_near_capacity_threshold: int = 80
    node_full_threshold: int = 95

    # Rate Limiting
    rate_limit_messages: int = 30
    rate_limit_window: int = 60

    # Уведомления — строка, список через property
    notify_days_before: str = "3,1"

    @property
    def notify_days_list(self) -> List[int]:
        try:
            return [int(x.strip()) for x in self.notify_days_before.split(",") if x.strip()]
        except Exception:
            return [3, 1]

    # Мониторинг
    node_alert_threshold: int = 80

    # Общие
    environment: str = "production"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
