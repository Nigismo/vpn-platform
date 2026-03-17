# ============================================================
# Stage 1: Builder — устанавливаем зависимости
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости в отдельный каталог
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: Runtime — минимальный образ для продакшена
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Устанавливаем только runtime-зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные пакеты из builder
COPY --from=builder /install /usr/local

# Создаём непривилегированного пользователя
RUN groupadd -r vpnbot && useradd -r -g vpnbot -d /app -s /sbin/nologin vpnbot

# Копируем исходный код приложения
COPY --chown=vpnbot:vpnbot . .

# Создаём директорию для логов
RUN mkdir -p /app/logs && chown vpnbot:vpnbot /app/logs

# Переключаемся на непривилегированного пользователя
USER vpnbot

# Метаданные образа
LABEL maintainer="VPN Platform" \
      version="1.0.0" \
      description="VPN Telegram Bot Platform"

# Healthcheck — проверяем что процесс жив
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import asyncio, redis.asyncio as redis; asyncio.run(redis.from_url('redis://redis:6379').ping())" || exit 1

# Запускаем бота
CMD ["python", "-m", "bot.main"]
