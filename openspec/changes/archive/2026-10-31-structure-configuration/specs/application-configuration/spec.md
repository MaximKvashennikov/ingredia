# Application configuration

## Purpose

Разделять настройки компонентов и безопасно загружать вложенные переменные окружения,
сохраняя проверку обязательных данных и маскирование секретов.

## ADDED Requirements

### Requirement: Nested component models

Система SHALL иметь отдельные модели Telegram user/admin/trial, AI, database и logging.
Разделитель env SHALL быть __; значение процесса SHALL переопределять отдельное поле dotenv.

#### Scenario: Nested fields
- **WHEN** заданы TELEGRAM__USER__TOKEN и AI__GROQ__API_KEY
- **THEN** значения попадают в соответствующие вложенные модели.

#### Scenario: Partial override
- **WHEN** процесс задаёт AI__PROVIDER поверх dotenv
- **THEN** соседние credentials и defaults сохраняются.

### Requirement: Validated credentials

Пользовательские token и username SHALL быть обязательными. До Telegram-подключения SHALL
проверяться ключ выбранного провайдера; неактивный ключ необязателен.

#### Scenario: Missing user credentials
- **WHEN** обязательные пользовательские настройки отсутствуют
- **THEN** загрузка отклоняется без сетевого подключения.

#### Scenario: Optional administrator
- **WHEN** административный токен не задан
- **THEN** пользовательский бот может работать без административного доступа.

### Requirement: Secret masking and deployment parity

Ключи и URL БД SHALL иметь SecretStr и маскироваться.
Compose SHALL использовать те же вложенные имена, что локальный запуск.

#### Scenario: Representation
- **WHEN** формируется repr настроек
- **THEN** реальные ключи, токены и URL БД не раскрываются.

#### Scenario: Container database
- **WHEN** запускаются приложение и миграции Compose
- **THEN** DATABASE__URL указывает на внутренний PostgreSQL без изменения локального URL.
