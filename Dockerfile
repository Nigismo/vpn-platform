FROM python:3.11 AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Просто копируем файлы, ничего не устанавливая на этапе сборки!
COPY . .

# ТРЮК: Устанавливаем библиотеки при каждом ЗАПУСКЕ контейнера
ENTRYPOINT ["sh", "-c", "pip install --no-cache-dir -r requirements.txt && exec \"$@\"", "--"]

# Запуск бота
CMD ["python", "-m", "bot.main"]
