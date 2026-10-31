# Recognition provider selection

## Purpose

Переключать фото и текст между сохранённым GLM и Qwen без изменения прикладного сценария.

## ADDED Requirements

### Requirement: Explicit provider selection

Система SHALL выбирать провайдера фото и текста через валидированную настройку AI__PROVIDER.
При отсутствии ключа выбранного провайдера SHALL возникать ошибка конфигурации до подключения
Telegram. Ключ неактивного провайдера SHALL не быть обязательным.

#### Scenario: Select Qwen without a GLM key
- **WHEN** выбран groq и задан его ключ, а AI__ZAI__API_KEY отсутствует
- **THEN** оба порта используют Groq/Qwen и возвращают прежние доменные наблюдения.

#### Scenario: Missing selected credentials
- **WHEN** ключ выбранного провайдера отсутствует или пуст
- **THEN** запуск отклоняется без сетевого подключения Telegram и без переключения на другой API.

#### Scenario: Return to GLM
- **WHEN** выбран zai и сохранён ключ Z.ai
- **THEN** фото использует прежнюю GLM vision, а текст — прежнюю GLM text через тот же контракт.

### Requirement: Safe provider failures without fallback

Система SHALL проверять ответы локальной доменной схемой и ограничивать сетевые операции.
Ошибка или исчерпание квоты SHALL не вызывать запрос к другому провайдеру, платной модели
или автоматическое пополнение. Секреты и содержимое ответа SHALL не попадать в сообщения об ошибке.

#### Scenario: Groq quota or regional refusal
- **WHEN** выбранный API отклоняет запрос из-за квоты или отсутствия доступа
- **THEN** пользователь получает безопасную категорию ошибки, GLM не вызывается.

#### Scenario: Invalid provider response
- **WHEN** ответ оборван, превышает предел размера или нарушает доменную схему
- **THEN** распознавание завершается ошибкой без добавления выдуманных продуктов.

#### Scenario: Provider redirects a request
- **WHEN** выбранный сервис возвращает перенаправление на другой адрес
- **THEN** приложение не передаёт секрет и данные по этому адресу.

### Requirement: Safe recognition diagnostics

Система SHALL записывать категорию отказа фото и текста, HTTP-статус провайдера и только
известный код ошибки. Тела сообщений, изображений и ответов API SHALL не попадать в диагностику.

#### Scenario: Vision schema rejected
- **WHEN** Groq возвращает HTTP 400 и json_validate_failed
- **THEN** лог содержит статус и invalid_response без тела ответа и модельного вывода.

#### Scenario: Unknown provider error code
- **WHEN** API возвращает неизвестное строковое значение code
- **THEN** оно заменяется в логе на other, даже если проходит проверку длины и символов.
