-- init.sql — Инициализация базы данных при первом запуске
-- Этот файл выполняется автоматически при создании контейнера PostgreSQL

-- Создаём расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Вставляем тестовую VPN-ноду (замените на реальные данные)
-- INSERT INTO vpn_nodes (name, country, country_emoji, ip_address, marzban_url, marzban_username, marzban_password, max_users)
-- VALUES ('NL-1', 'Netherlands', '🇳🇱', '1.2.3.4', 'https://panel.yourdomain.com', 'admin', 'your_password', 500);

-- Вставляем домены для ротации (замените на реальные)
-- INSERT INTO vpn_domains (domain, is_active, priority) VALUES
-- ('sub1.yourdomain.com', true, 10),
-- ('sub2.yourdomain.com', true, 5),
-- ('sub3.yourdomain.com', true, 1);
