# Разработка ingredia

Реализована первая часть Telegram MVP с PostgreSQL и отдельным админ-ботом.
[Запуск и текущие ограничения](telegram-foundation.md).
Сохранена фото-проба распознавания через GLM без записи результата в БД.
[Запуск и ограничения](photo-trial.md). Полный MVP ещё не реализован; интерфейсы планируются только
в Telegram.

## Подготовка Python-окружения

В корне проекта выполните:

```powershell
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

В локальном `.env` задайте TELEGRAM__USER__TOKEN, TELEGRAM__USER__USERNAME и AI__ZAI__API_KEY.
Файл исключён из Git; переменные окружения имеют приоритет.

Настройки доступны через `from ingredia.settings import get_settings`.
Токен Telegram и ключ Z.ai используют `SecretStr` и маскируются при выводе настроек.
Обязателен ключ выбранного AI-провайдера: AI__GROQ__API_KEY для groq или AI__ZAI__API_KEY для zai.

Настройки будущего админ-бота: TELEGRAM__ADMIN__TOKEN (SecretStr),
TELEGRAM__ADMIN__USERNAME и TELEGRAM__ADMIN__USER_IDS (JSON-массив числовых ID).
Пустой список запрещает доступ. Токен подготовлен в локальном .env, административный transport реализован.
Текущая команда запускает только пользовательскую фото-пробу; админ-бот не запускается
автоматически.
После каждой реализации применять code-reviewer; инструкции находятся в AGENTS.md.
Для запуска выполните: uv run --locked python -m ingredia.

## Проверки Python

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy ingredia
```

Настройки Ruff, Google-style докстрингов и mypy находятся в `pyproject.toml` . Автоматизированные
тесты приложения после их появления запускаются через `uv run pytest` .

Установка и ручной запуск Git hooks:

```powershell
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
```

## Спецификации

- [Продуктовый change](../openspec/changes/define-fridge-mvp/proposal.md) ,
  [архитектура](../openspec/changes/define-fridge-mvp/design.md) и
  [задачи MVP](../openspec/changes/define-fridge-mvp/tasks.md) .
- [Техническая основа][doc-link-1],
  [архитектура](../openspec/changes/establish-platform-foundation/design.md) и
  [задачи](../openspec/changes/establish-platform-foundation/tasks.md) .
- [Исследование продукта](product-discovery-2026-10-29.md) ,
  [облачные AI-модели](ai-model-research-2026-10-29.md) и
  [результаты проверки документов](spec-validation.md) .

Проверка OpenSpec без глобальной установки CLI:

```powershell
$env:DO_NOT_TRACK = '1'
npm exec --yes --package=@fission-ai/openspec -- openspec validate --all --strict
```

Структура следует официальной [схеме spec-driven](https://openspec.dev/docs/schemas/spec-driven) ,
настройки — [формату config.yaml](https://openspec.dev/docs/configuration/config-yaml) . Валидация
проверяет документы, а не готовность приложения.

Документы в `openspec/changes/` описывают запланированное поведение. Каталог `openspec/specs/`
заполняется после реализации, проверки и архивирования change. Инструкции для агента, стек,
ограничения работ и проектные скиллы находятся в [AGENTS.md](../AGENTS.md) .

[doc-link-1]: ../openspec/changes/establish-platform-foundation/proposal.md

## Провайдер распознавания

[Переключение GLM и Qwen](ai-providers.md): AI__PROVIDER, отдельные ключи и текущий статус.

## Вложенные настройки

Модели находятся в ingredia/settings: telegram, ai, database и logging.
Корневой Settings объединяет их и задаёт разделитель __. Имена — в .env.example.
Процесс переопределяет отдельное поле dotenv, не стирая соседние значения.
POSTGRES_PASSWORD сохраняет стандартное имя для образа PostgreSQL.
Локальный env уже переведён; новые ключи для этого рефакторинга не нужны.
