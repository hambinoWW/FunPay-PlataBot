# PLATA

**Автоматизация FunPay с удобной Telegram-панелью.**

Обновления: [@funpayplata](https://t.me/funpayplata) · Плагины: [@quantumdeals](https://t.me/quantumdeals) · Разработчик: [@hambinoww](https://t.me/hambinoww)

PLATA — самостоятельный self-hosted бот для автоматизации FunPay. Каждый пользователь запускает собственную копию проекта со своими аккаунтами, настройками и Telegram-ботом.

## Возможности

- автоматическая выдача товаров и автоответы покупателям;
- автоподнятие, восстановление и отключение лотов;
- приветствия, шаблоны сообщений, чёрный список и прокси;
- уведомления о сообщениях, заказах, отзывах и выдаче;
- статистика продаж, оборота и заказов;
- проверка подключения FunPay и состояния аккаунтов;
- резервное копирование конфигурации, товаров и данных;
- управление через inline-кнопки Telegram.

## Центр аккаунтов

Один экземпляр PLATA поддерживает несколько FunPay-аккаунтов. Для каждого профиля отдельно хранятся golden key, конфиги, товары, настройки модулей и статистика.

Подключение и управление выполняются через раздел `👤 Аккаунты` в Telegram-панели. Добавление аккаунта проходит пошагово через кнопки меню.

## Telegram-панель

Откройте панель командой `/menu` или `/start`.

- `⚙️ Автоматизация` — автоматические функции FunPay;
- `🔔 Уведомления` — настройка событий;
- `👤 Аккаунты` — подключение и состояние профилей;
- `📊 Статистика` — продажи и аналитика;
- `🧩 Плагины` — расширения;
- `🦊 Модули` — встроенные функции PLATA;
- `Больше` — конфиги, прокси и язык.

Доступ к панели получают только авторизованные пользователи. Владелец публичной сборки: Telegram ID `5264940850`.

## Встроенные модули

- `🔔 Напоминание о подтверждении заказа` — отправляет покупателю сообщение со ссылкой на конкретный заказ;
- `⭐ Ответы на отзывы` — ответы для разных оценок и удалённых отзывов;
- `📋 Старые заказы` — просмотр старых заказов.

Настройки модулей изолированы по аккаунтам и сохраняются локально.

## Плагины и совместимость

PLATA сохраняет совместимость с плагинами FunPay Cardinal:

```python
from cardinal import Cardinal
```

Поддерживаются прежние метаданные, обработчики `BIND_TO_*`, Telegram-модули и стандартный API плагинов. Подробности: [PLUGIN_COMPATIBILITY.md](PLUGIN_COMPATIBILITY.md).

Плагин выполняет произвольный Python-код с правами пользователя. Устанавливайте расширения только из доверенных источников.

## ⬇️ Установка

Для Linux-сервера рекомендуется Ubuntu 22.04–24.04. Выберите любого VPS-провайдера, которому доверяете. Остальные параметры зависят от количества аккаунтов и нагрузки.

### 🔷 Windows

1. Скачайте и установите [Python 3.11.0](https://www.python.org/downloads/release/python-3110/).
2. На первом экране установщика включите `Add python.exe to PATH`.
3. Скачайте архив PLATA из раздела [Releases](https://github.com/hambinoWW/FunPay-PlataBot/releases) или клонируйте репозиторий:

   ```powershell
   git clone https://github.com/hambinoWW/FunPay-PlataBot.git
   cd FunPay-PlataBot
   ```

4. Если используете ZIP, распакуйте его и перейдите в папку проекта.
5. Запустите `Setup.bat` и дождитесь установки зависимостей.
6. Закройте окно установки и запустите `Start.bat`.
7. Пройдите мастер настройки в консоли: FunPay golden key, Telegram Bot Token и пароль панели.
8. После запуска откройте Telegram и отправьте PLATA команду `/menu`.

### ♨️ Linux (Ubuntu)

```bash
sudo apt update
sudo apt install -y git python3.11 python3.11-venv python3-pip
git clone https://github.com/hambinoWW/FunPay-PlataBot.git
cd FunPay-PlataBot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python main.py
```

Для фоновой работы используйте `PLATA@.service` или Docker. Не запускайте несколько копий с одним Telegram Bot Token.

### 🐳 Docker

Установите Docker Desktop (Windows/macOS) или Docker Engine и Docker Compose (Linux), затем перейдите в папку проекта:

```bash
git clone https://github.com/hambinoWW/FunPay-PlataBot.git
cd FunPay-PlataBot
docker compose build
```

При первом запуске PLATA запрашивает настройки через консоль, поэтому используйте разовый интерактивный контейнер:

```bash
docker compose run --rm plata
```

После завершения мастера запускайте PLATA в фоне:

```bash
docker compose up -d
```

Полезные команды:

```bash
# Логи
docker compose logs -f plata

# Остановить
docker compose down

# Перезапустить
docker compose restart plata

# Статус и healthcheck
docker compose ps
```

Контейнер запускается от непривилегированного пользователя. Папки `configs`, `logs`, `storage` и `plugins` монтируются с хоста в контейнер, поэтому данные сохраняются между перезапусками и пересборками образа.

## Безопасность

- не публикуйте `configs/`, golden key, Telegram token и `storage/`;
- ограничьте доступ к Telegram-панели;
- при утечке golden key замените его в FunPay;
- делайте backup перед обновлением и установкой плагинов;
- публичный архив не содержит пользовательских данных, секретов и удалённого канала объявлений;
- backup проверяется по manifest и безопасным путям.

PLATA — независимый проект и не является официальным продуктом FunPay.

## Версия

`0.1.1`

## Помощь

Обновления: [@funpayplata](https://t.me/funpayplata)  
Плагины: [@quantumdeals](https://t.me/quantumdeals)  
Разработчик: [@hambinoww](https://t.me/hambinoww)
