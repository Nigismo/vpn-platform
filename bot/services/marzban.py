"""
bot/services/marzban.py — Клиент для работы с Marzban API.
"""

from __future__ import annotations

import asyncio
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger

from config import settings


class MarzbanAPIError(Exception):
    pass


class MarzbanClient:

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _authenticate(self) -> str:
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
                    raise MarzbanAPIError(f"Ошибка аутентификации: {resp.status} — {text}")
                data = await resp.json()
                self._token = data["access_token"]
                self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=1380)
                logger.debug(f"✅ Marzban JWT обновлён")
                return self._token
        except aiohttp.ClientError as exc:
            raise MarzbanAPIError(f"Ошибка подключения к Marzban: {exc}") from exc

    async def _request(self, method: str, endpoint: str, retries: int = 3, **kwargs: Any) -> Any:
        token = await self._authenticate()
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}
        auth_retried = False  # Флаг: 401 уже обрабатывали

        for attempt in range(1, retries + 1):
            try:
                async with session.request(method, url, headers=headers, **kwargs) as resp:
                    # FIX: обновляем токен при 401 только один раз
                    if resp.status == 401 and not auth_retried:
                        self._token = None
                        token = await self._authenticate()
                        headers["Authorization"] = f"Bearer {token}"
                        auth_retried = True
                        continue

                    if resp.status == 404:
                        raise MarzbanAPIError(f"NOT_FOUND:{endpoint}")

                    if resp.status >= 400:
                        text = await resp.text()
                        raise MarzbanAPIError(f"Marzban {method} {endpoint}: {resp.status} — {text}")

                    if resp.content_type == "application/json":
                        return await resp.json()
                    return await resp.text()

            except aiohttp.ClientError as exc:
                if attempt == retries:
                    raise MarzbanAPIError(f"Ошибка запроса (попытка {attempt}): {exc}") from exc
                wait_time = 2 ** attempt
                logger.warning(f"Ошибка Marzban, повтор через {wait_time}с: {exc}")
                await asyncio.sleep(wait_time)

        raise MarzbanAPIError("Все попытки запроса исчерпаны")

    async def create_user(
        self,
        username: str,
        expire_days: int,
        ip_limit: int = 3,
        data_limit_gb: int = 0,
    ) -> dict:
        expire_timestamp = int(
            (datetime.now(timezone.utc) + timedelta(days=expire_days)).timestamp()
        )
        payload = {
            "username": username,
            "proxies": {"vless": {"flow": "xtls-rprx-vision"}},
            # ⚠️ ВАЖНО: названия inbounds должны совпадать с вашей панелью Marzban
            "inbounds": {"vless": ["VLESS TCP REALITY", "VLESS gRPC REALITY"]},
            "expire": expire_timestamp,
            "data_limit": data_limit_gb * 1024 ** 3 if data_limit_gb > 0 else 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "ip_limit": ip_limit,
        }
        result = await self._request("POST", "/user", json=payload)
        logger.info(f"✅ Marzban: создан пользователь {username}")
        return result

    async def get_user(self, username: str) -> dict:
        return await self._request("GET", f"/user/{username}")

    async def user_exists(self, username: str) -> bool:
        """Проверяем существование пользователя — не глотаем все ошибки подряд."""
        try:
            await self._request("GET", f"/user/{username}")
            return True
        except MarzbanAPIError as exc:
            if "NOT_FOUND" in str(exc):
                return False
            raise  # Прочие ошибки (сеть, auth) — пробрасываем наверх

    async def update_user_expire(self, username: str, new_expire_timestamp: int) -> dict:
        payload = {"expire": new_expire_timestamp}
        result = await self._request("PUT", f"/user/{username}", json=payload)
        logger.info(f"🔄 Marzban: обновлён expire для {username}")
        return result

    async def delete_user(self, username: str) -> None:
        await self._request("DELETE", f"/user/{username}")
        logger.info(f"🗑️ Marzban: удалён пользователь {username}")

    async def reset_user_traffic(self, username: str) -> None:
        await self._request("POST", f"/user/{username}/reset")

    async def get_subscription_url(self, username: str, domain: Optional[str] = None) -> str:
        # FIX: используем vpn_domains_list вместо vpn_domains (строки)
        if domain:
            base = f"https://{domain}"
        elif settings.vpn_domains_list:
            base = f"https://{random.choice(settings.vpn_domains_list)}"
        else:
            base = settings.marzban_url
        return f"{base}/sub/{username}"

    async def get_system_stats(self) -> dict:
        return await self._request("GET", "/system")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def generate_vpn_username(telegram_id: int) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"u{telegram_id}_{suffix}"


marzban_client = MarzbanClient(
    base_url=settings.marzban_url,
    username=settings.marzban_username,
    password=settings.marzban_password,
)

# Алиас для обратной совместимости с упрощённым buy.py
marzban_service = marzban_client
