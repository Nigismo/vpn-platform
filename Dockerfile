# Берем полный образ (чтобы ujson и asyncpg компилировались без проблем)
FROM python:3.11 AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Копируем только список зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки ОДИН РАЗ на этапе сборки образа!
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код
COPY . .


# Запуск бота
CMD ["python", "-m", "bot.main"]
