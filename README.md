# ingredia

ingredia — виртуальный холодильник с Telegram-ботом: распознавание продуктов по фото или голосу, учёт запасов и сроков, подбор рецептов и избранные блюда. ВК рассматривается только как будущее расширение через адаптер.

Статус на 2026-10-29: подготовлены черновики технической основы, Docker-развёртывания и двух продуктовых сценариев. Из кода настроена только загрузка Telegram-токена; приложение и бот ещё не реализованы.

## Конфигурация

| Область | Решение пользователя |
| --- | --- |
| Backend | FastAPI |
| Frontend | React + TypeScript |
| Основная БД | PostgreSQL; медиа отдельно |
| Запуск и развёртывание | Docker Compose локально и для первого сервера; реализация запланирована |
| Будущий клиент | Android через общий API; вне текущего MVP |
| Python | uv |
| Автоматизированный QA | Только pytest, через `uv run pytest` |
| Безопасность | Security best practices с проверяемыми требованиями |
| UX/UI | Релевантные skills; без скриншотного тестирования |
| Интеграции | Расширяемая архитектура подключения ботов |
| Планирование | OpenSpec для фич и фаз |

## Документы

- [Спецификации MVP](openspec/changes/define-fridge-mvp/proposal.md) — два пользовательских сценария и шесть возможностей, включая избранное и админку пользователей.
- [Админка пользователей](openspec/changes/define-fridge-mvp/specs/user-administration/spec.md) — список/поиск, карточка, блокировка/разблокировка, права и аудит.
- [Продуктовая архитектура](openspec/changes/define-fridge-mvp/design.md) — партии продуктов, распознавание, рецепты и персональные исправления.
- [План задач MVP](openspec/changes/define-fridge-mvp/tasks.md) — будущая реализация, сгруппированная по фазам.
- [Инструкции проекта](AGENTS.md) — ограничения, действующие и после перезапуска приложения.
- [Продуктовый контекст](docs/product-brief.md) — известные данные и вопросы, влияющие на MVP.
- [Product discovery](docs/product-discovery-2026-10-29.md) — наблюдения по альтернативам и предложения для проверки.
- [План фаз](openspec/roadmap.md) — зависимости и критерии перехода.
- [Предложение](openspec/changes/establish-platform-foundation/proposal.md) — границы базового change.
- [Архитектура](openspec/changes/establish-platform-foundation/design.md) — адаптеры ботов, безопасность, данные и QA.
- [Будущие задачи](openspec/changes/establish-platform-foundation/tasks.md) — задачи реализации; все остаются невыполненными.
- [Подключение ботов](openspec/changes/establish-platform-foundation/specs/bot-connections/spec.md).
- [Безопасность](openspec/changes/establish-platform-foundation/specs/platform-security/spec.md).
- [UX управления подключениями](openspec/changes/establish-platform-foundation/specs/connection-management-ux/spec.md).
- [Контракт клиентов](openspec/changes/establish-platform-foundation/specs/client-api/spec.md) — общий API для веба и будущего Android.
- [Контейнерный запуск](openspec/changes/establish-platform-foundation/specs/container-deployment/spec.md) — локальный запуск и первое серверное развёртывание.
- [Результаты проверки](docs/spec-validation.md) — строгая валидация двух changes и границы проверенного.

## Проверка OpenSpec

Структура следует официальной [схеме spec-driven](https://openspec.dev/docs/schemas/spec-driven); настройки — [формату config.yaml](https://openspec.dev/docs/configuration/config-yaml).

После появления OpenSpec CLI в окружении проверка change выполняется командой:

```text
openspec validate establish-platform-foundation --strict
openspec validate define-fridge-mvp --strict
```

Глобальные CLI `openspec` и `uv` при первичной проверке не найдены в PATH. Для валидации спецификаций OpenSpec запускался временно через npm exec. Во время подготовки документов код не создавался; позднее по отдельному запросу добавлена конфигурация Telegram.

## Настройки Telegram

Токен бота `ingredia_helper_bot` хранится локально в `.env`; файл исключён из Git. Для другого окружения скопируйте [.env.example](.env.example) в `.env` и задайте свой токен. Переменные окружения с теми же именами имеют приоритет над файлом.

Зависимость объявлена в `pyproject.toml` и закреплена в `uv.lock`. После `uv sync` настройки доступны через `from ingredia.settings import get_settings`. Токен представлен типом `SecretStr`; раскрывать значение через `get_secret_value()` следует только в месте вызова Telegram API. Отсутствующий токен вызовет ошибку загрузки настроек. Проверено в проектном `.venv`: имя бота загружается, токен в строковом представлении замаскирован.

Документы в `openspec/changes/` описывают предлагаемое будущее поведение. Каталог принятых спецификаций `openspec/specs/` будет заполняться после реализации, проверки и архивирования соответствующего change.

## Проверки Python

После `uv sync` запустите `uv run --locked ruff check .`, `uv run --locked ruff format --check .` и `uv run --locked mypy ingredia`. Правила Ruff (включая Google-style докстринги) и mypy находятся в `pyproject.toml`. Для Git-хука используйте `uv run --locked pre-commit install`, для ручной проверки всех файлов — `uv run --locked pre-commit run --all-files`. Автоматические тесты приложения — только pytest.

## Проектные скиллы

Скиллы Codex находятся в [.agents/skills](.agents/skills) и относятся только к этому репозиторию:

- pytest-test-authoring — проектирование и написание pytest-тестов после разрешения реализации.
- qa-verification — запуск проверок и честный отчёт о непроверенных областях.
- react-ux — UX/UI для React/TypeScript, доступность и ручная приёмка без скриншотных тестов.
- product-discovery — исследование рынка и обоснованные продуктовые предложения.
- openspec-feature-planning — оформление фич и фаз в OpenSpec.
- security-best-practices — проверка безопасности FastAPI и React (готовый curated skill OpenAI).

Наличие скиллов не означает разрешения на реализацию: текущий этап по-прежнему ограничен спецификациями.
