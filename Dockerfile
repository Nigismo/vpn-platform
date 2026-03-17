# Берем ПОЛНЫЙ образ со всеми компиляторами на борту
FROM python:3.11

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Копируем список и обновляем сам установщик pip (это важно!)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Запуск
CMD ["python", "main.py"]
