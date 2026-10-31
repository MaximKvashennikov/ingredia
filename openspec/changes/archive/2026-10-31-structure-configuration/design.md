# Design

Корневой Settings в ingredia/settings/base.py наследует BaseSettings и объединяет модели
Telegram user/admin/trial, AI, database и logging. Вложенные модели — отдельные BaseModel.
env_nested_delimiter равен __; процесс переопределяет отдельное поле dotenv.

User credentials обязательны, административный токен необязателен, пустой allowlist запрещает
доступ. Требуется ключ только выбранного AI. SecretStr и маскирование сохранены.

Compose переопределяет DATABASE__URL внутренним адресом. Локальные секретные значения сохранены.
POSTGRES_PASSWORD остаётся стандартной переменной образа PostgreSQL.
TEST_DATABASE_URL относится к pytest, не к настройкам приложения.
