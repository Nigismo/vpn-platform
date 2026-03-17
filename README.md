# 🔒 VPN Platform — Production Telegram Bot

Полная платформа для продажи VPN-подписок через Telegram бота.
Построена на aiogram 3, PostgreSQL, Redis, Marzban, Xray.

## 📦 Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Бот | aiogram 3.13, Python 3.11+ |
| База данных | PostgreSQL 16 + SQLAlchemy 2.0 |
| Кэш / Rate limit | Redis 7 |
| VPN панель | Marzban + Xray-core |
| Платежи | YooKassa, СБП |
| Контейнеры | Docker + Docker Compose |
| Деплой | Portainer |

## 🚀 Быстрый старт

### 1. Клонирование и настройка окружения

```bash
git clone https://github.com/yourorg/vpn-platform.git
cd vpn-platform
cp .env.example .env
nano .env   # Заполните все переменные
```

### 2. Обязательные переменные .env

```env
BOT_TOKEN=           # Токен от @BotFather
ADMIN_IDS=           # Ваш Telegram ID (узнать: @userinfobot)
POSTGRES_PASSWORD=   # Придумайте надёжный пароль
REDIS_PASSWORD=      # Придумайте надёжный пароль
MARZBAN_URL=         # https://panel.yourdomain.com
MARZBAN_USERNAME=    # Логин от Marzban панели
MARZBAN_PASSWORD=    # Пароль от Marzban панели
VPN_DOMAINS=         # Домены для подписок (через запятую)
```

### 3. Запуск через Docker Compose

```bash
# Сборка и запуск всех сервисов
docker compose up -d --build

# Применение миграций БД
docker compose run --rm migrate

# Просмотр логов бота
docker compose logs -f bot
```

## 🏗️ Архитектура

```
vpn_platform/
├── bot/
│   ├── handlers/          # Обработчики команд и callback
│   │   ├── start_handler.py
│   │   ├── buy_handler.py
│   │   ├── vpn_handler.py
│   │   ├── profile_handler.py
│   │   └── admin_handler.py
│   ├── services/          # Бизнес-логика
│   │   ├── marzban.py     # Клиент Marzban API
│   │   ├── node_balancer.py
│   │   ├── payment.py     # YooKassa + СБП
│   │   ├── subscription.py
│   │   └── user_service.py
│   ├── keyboards/         # Inline и Reply клавиатуры
│   ├── middlewares/       # Rate limit, auth, DB session
│   ├── tasks/             # Фоновые задачи (APScheduler)
│   └── main.py            # Точка входа
├── database/
│   ├── models.py          # SQLAlchemy ORM модели
│   └── session.py         # Управление сессиями
├── migrations/            # Alembic миграции
├── config.py              # Pydantic Settings
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## 🌐 Настройка доменов и SSL

### Настройка Nginx (рекомендуется)

```nginx
server {
    server_name sub1.yourdomain.com;

    location /sub/ {
        proxy_pass http://marzban:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
}
```

### Получение SSL сертификата

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d sub1.yourdomain.com -d sub2.yourdomain.com
```

## 🖥️ Установка Marzban

```bash
# Установка на отдельный VPS
sudo bash -c "$(curl -sL https://github.com/Gozargah/Marzban-scripts/raw/master/marzban.sh)" @ install

# Создание первого администратора
marzban cli admin create --sudo
```

### Настройка Xray (VLESS + REALITY)

В файле `/opt/marzban/xray_config.json` добавьте inbound:

```json
{
  "tag": "VLESS TCP REALITY",
  "listen": "0.0.0.0",
  "port": 443,
  "protocol": "vless",
  "settings": {
    "clients": [],
    "decryption": "none"
  },
  "streamSettings": {
    "network": "tcp",
    "security": "reality",
    "realitySettings": {
      "show": false,
      "dest": "www.google.com:443",
      "xver": 0,
      "serverNames": ["www.google.com"],
      "privateKey": "YOUR_PRIVATE_KEY",
      "shortIds": [""]
    }
  },
  "sniffing": {"enabled": true, "destOverride": ["http", "tls"]}
}
```

## 🐳 Деплой через Portainer

1. Откройте Portainer → **Stacks** → **Add stack**
2. Назовите стек: `vpn-platform`
3. Вставьте содержимое `docker-compose.yml`
4. В разделе **Environment variables** добавьте все переменные из `.env`
5. Нажмите **Deploy the stack**

## 📊 Балансировка нод

Добавление новой ноды через SQL:

```sql
INSERT INTO vpn_nodes (name, country, country_emoji, ip_address, marzban_url, marzban_username, marzban_password, max_users)
VALUES ('NL-1', 'Netherlands', '🇳🇱', '1.2.3.4', 'https://panel-nl.yourdomain.com', 'admin', 'password', 500);
```

Алгоритм балансировки:
- Выбирается нода с наименьшей загрузкой
- При > 80% загрузки — статус `near_capacity`  
- При > 95% — статус `full`, новые пользователи не назначаются

## 💳 Настройка YooKassa

1. Зарегистрируйтесь на [yookassa.ru](https://yookassa.ru)
2. Получите Shop ID и Secret Key в личном кабинете
3. Добавьте в `.env`:
   ```
   YOOKASSA_SHOP_ID=your_shop_id
   YOOKASSA_SECRET_KEY=your_secret_key
   ```

## 🔄 Управление миграциями

```bash
# Создать новую миграцию
docker compose run --rm bot alembic revision --autogenerate -m "add_new_field"

# Применить все миграции
docker compose run --rm bot alembic upgrade head

# Откатить последнюю миграцию
docker compose run --rm bot alembic downgrade -1
```

## 📈 Мониторинг

Планировщик выполняет следующие задачи:

| Задача | Расписание |
|--------|-----------|
| Уведомления об истечении | Каждые 6 часов |
| Удаление истёкших подписок | Ежедневно в 02:00 |
| Синхронизация нод | Ежедневно в 03:00 |
| Мониторинг нагрузки | Каждые 30 минут |

Администраторы получают Telegram-алерт при загрузке ноды > 80%.

## 🔐 Безопасность

- Все пользователи проверяются через `BlockedUserMiddleware`
- Rate limiting: 30 сообщений/минуту на пользователя (Redis)
- Бот работает от непривилегированного пользователя в Docker
- Пароли и токены только через переменные окружения
- JWT токены Marzban кешируются и автообновляются

## 🆘 Troubleshooting

**Бот не запускается:**
```bash
docker compose logs bot --tail=50
```

**Ошибки подключения к БД:**
```bash
docker compose exec postgres psql -U vpnuser -d vpnplatform -c "\dt"
```

**Сброс Redis:**
```bash
docker compose exec redis redis-cli -a $REDIS_PASSWORD FLUSHALL
```
