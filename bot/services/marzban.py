"""
bot/services/marzban.py — Клиент для работы с Marzban API.
Создание, управление и удаление VPN-пользователей через панель Marzban.
"""

from __future__ import annotations

import asyncio
import random
import string
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger

from config import settings


class MarzbanAPIError(Exception):
    """Исключение для ошибок Marzban API."""
    pass


class MarzbanClient:
    """
    Асинхронный клиент для работы с Marzban REST API.
    Поддерживает автоматическое обновление JWT токена и retry логику.
    """

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получаем или создаём HTTP-сессию."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _authenticate(self) -> str:
        """
        Аутентификация в Marzban и получение JWT токена.
        Кешируем токен до его истечения.
        """
        # Проверяем, не истёк ли токен (с запасом 60 секунд)
        if self._token and self._token_expires:
            remaining = (self._token_expires - datetime.now(timezone.utc)).total_seconds()
            if remaining > 60:
                return self._token

        session = await self._get_session()
        url = f"{self.base_url}/api/admin/token"

        try:
            async with session.post(
                url,
                data={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise MarzbanAPIError(f"Ошибка аутентификации Marzban: {resp.status} — {text}")

                data = await resp.json()
                self._token = data["access_token"]
                # Токены Marzban живут 1440 минут = 24 часа
                from datetime import timedelta
                self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=1380)
                logger.debug(f"✅ Marzban JWT обновлён для {self.base_url}")
                return self._token

        except aiohttp.ClientError as exc:
            raise MarzbanAPIError(f"Ошибка подключения к Marzban: {exc}") from exc

    async def _request(
        self,
        method: str,
        endpoint: str,
        retries: int = 3,
        **kwargs: Any,
    ) -> Any:
        """
        Выполняем HTTP-запрос к Marzban API с retry логикой.
        При 401 автоматически обновляем токен.
        """
        token = await self._authenticate()
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        for attempt in range(1, retries + 1):
            try:
                async with session.request(
                    method, url, headers=headers, **kwargs
                ) as resp:
                    # Если токен истёк — сбрасываем и повторяем
                    if resp.status == 401:
                        self._token = None
                        token = await self._authenticate()
                        headers["Authorization"] = f"Bearer {token}"
                        continue

                    if resp.status >= 400:
                        text = await resp.text()
                        raise MarzbanAPIError(
                            f"Marzban API {method} {endpoint}: {resp.status} — {text}"
                        )

                    if resp.content_type == "application/json":
                        return await resp.json()
                    return await resp.text()

            except aiohttp.ClientError as exc:
                if attempt == retries:
                    raise MarzbanAPIError(f"Ошибка запроса к Marzban (попытка {attempt}): {exc}") from exc
                wait_time = 2 ** attempt  # Экспоненциальный backoff
                logger.warning(f"Ошибка Marzban, повтор через {wait_time}с: {exc}")
                await asyncio.sleep(wait_time)

        raise MarzbanAPIError("Все попытки запроса к Marzban исчерпаны")

    # ----------------------------------------------------------
    # Методы управления пользователями
    # ----------------------------------------------------------

    async def create_user(
        self,
        username: str,
        expire_days: int,
        ip_limit: int = 3,
        data_limit_gb: int = 0,
    ) -> dict:
        """
        Создаём нового VPN пользователя в Marzban.
        Настраиваем все поддерживаемые протоколы: VLESS REALITY, gRPC, WS.
        """
        from datetime import timedelta

        expire_timestamp = int(
            (datetime.now(timezone.utc) + timedelta(days=expire_days)).timestamp()
        )

        payload = {
            "username": username,
            "proxies": {
                "vless": {
                    "flow": "xtls-rprx-vision",
                },
            },
            "inbounds": {
                "vless": ["VLESS TCP REALITY", "VLESS gRPC REALITY"],
            },
            "expire": expire_timestamp,
            "data_limit": data_limit_gb * 1024 ** 3 if data_limit_gb > 0 else 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "ip_limit": ip_limit,
        }

        result = await self._request("POST", "/user", json=payload)
        logger.info(f"✅ Marzban: создан пользователь {username} (expire: {expire_days}d)")
        return result

    async def get_user(self, username: str) -> dict:
        """Получаем информацию о пользователе Marzban."""
        return await self._request("GET", f"/user/{username}")

    async def update_user_expire(self, username: str, new_expire_timestamp: int) -> dict:
        """Обновляем дату истечения подписки пользователя."""
        payload = {"expire": new_expire_timestamp}
        result = await self._request("PUT", f"/user/{username}", json=payload)
        logger.info(f"🔄 Marzban: обновлён expire для {username}")
        return result

    async def delete_user(self, username: str) -> None:
        """Удаляем пользователя из Marzban."""
        await self._request("DELETE", f"/user/{username}")
        logger.info(f"🗑️ Marzban: удалён пользователь {username}")

    async def reset_user_traffic(self, username: str) -> None:
        """Сбрасываем трафик пользователя."""
        await self._request("POST", f"/user/{username}/reset")

    async def get_subscription_url(self, username: str, domain: Optional[str] = None) -> str:
        """
        Генерируем ссылку на подписку пользователя.
        Если передан домен — используем его для ротации.
        """
        # Выбираем домен: переданный или первый из настроек
        if domain:
            base = f"https://{domain}"
        elif settings.vpn_domains:
            base = f"https://{random.choice(settings.vpn_domains)}"
        else:
            base = settings.marzban_url

        return f"{base}/sub/{username}"

    async def get_users_count(self) -> int:
        """Получаем общее количество пользователей в Marzban."""
        data = await self._request("GET", "/users?limit=1")
        return data.get("total", 0)

    async def get_system_stats(self) -> dict:
        """Получаем системную статистику Marzban (трафик, онлайн и т.д.)."""
        return await self._request("GET", "/system")

    async def close(self) -> None:
        """Закрываем HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()


def generate_vpn_username(telegram_id: int) -> str:
    """
    Генерируем уникальный VPN логин для пользователя.
    Формат: u{telegram_id}_{случайный суффикс}
    Marzban требует только латинские буквы, цифры и подчёркивание.
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"u{telegram_id}_{suffix}"


# ----------------------------------------------------------
# Глобальный экземпляр клиента Marzban
# ----------------------------------------------------------
marzban_client = MarzbanClient(
    base_url=settings.marzban_url,
    username=settings.marzban_username,
    password=settings.marzban_password,
)
