# Берем полный образ со всеми компиляторами (решает проблемы с C/C++ расширениями)
FROM python:3.11 AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Копируем список
COPY requirements.txt .

# Обязательно обновляем pip перед установкой!
RUN pip install --no-cache-dir --upgrade pip

# Устанавливаем наши легкие зависимости (скомпилируются без проблем)
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY . .

# Запуск
CMD ["python", "main.py"]
