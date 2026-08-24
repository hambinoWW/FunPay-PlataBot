"""
В данном модуле написана подпрограмма первичной настройки PLATA.
"""

import os
from configparser import ConfigParser
import time
import telebot
from colorama import Fore, Style
from Utils.plata_tools import validate_proxy, hash_password, build_proxy, check_proxy
from Utils.config_loader import load_main_config

ORANGE = "\033[38;5;208m"


def setup_step(number: int, title: str, description: str) -> None:
    print(f"\n{ORANGE}{Style.BRIGHT}[Шаг {number}/5] {title}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{description}{Style.RESET_ALL}")


def setup_input(label: str = "Введите значение") -> str:
    return input(f"{ORANGE}> {Fore.WHITE}{label}: {Style.RESET_ALL}").strip()


def setup_error(text: str) -> None:
    print(f"{Fore.RED}Ошибка: {text}{Style.RESET_ALL}")

# locale#locale#locale
default_config = {
    "FunPay": {
        "golden_key": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "autoRaise": "0",
        "autoResponse": "0",
        "autoDelivery": "0",
        "multiDelivery": "0",
        "autoRestore": "0",
        "autoDisable": "0",
        "oldMsgGetMode": "0",
        "locale": "ru"
    },
    "Telegram": {
        "enabled": "0",
        "token": "",
        "secretKeyHash": "ХешСекретногоПароля",
        "blockLogin": "0",
        "proxy": ""
    },

    "BlockList": {
        "blockDelivery": "0",
        "blockResponse": "0",
        "blockNewMessageNotification": "0",
        "blockNewOrderNotification": "0",
        "blockCommandNotification": "0"
    },

    "NewMessageView": {
        "includeMyMessages": "1",
        "includeFPMessages": "1",
        "includeBotMessages": "0",
        "notifyOnlyMyMessages": "0",
        "notifyOnlyFPMessages": "0",
        "notifyOnlyBotMessages": "0",
        "showImageName": "1"
    },

    "Greetings": {
        "ignoreSystemMessages": "0",
        "onlyNewChats": "0",
        "sendGreetings": "0",
        "greetingsText": "Привет, $chat_name!",
        "greetingsCooldown": "2"
    },

    "OrderConfirm": {
        "watermark": "1",
        "sendReply": "0",
        "replyText": "$username, спасибо за подтверждение заказа $order_id!\nЕсли не сложно, оставь, пожалуйста, отзыв!"
    },

    "ReviewReply": {
        "star1Reply": "0",
        "star2Reply": "0",
        "star3Reply": "0",
        "star4Reply": "0",
        "star5Reply": "0",
        "star1ReplyText": "",
        "star2ReplyText": "",
        "star3ReplyText": "",
        "star4ReplyText": "",
        "star5ReplyText": "",
    },

    "Proxy": {
        "enable": "0",
        "proxy": "",
        "check": "0"
    },

    "Other": {
        "watermark": "🦊",
        "requestsDelay": "4",
        "language": "ru"
    }
}


def create_configs():
    if not os.path.exists("configs/auto_response.cfg"):
        with open("configs/auto_response.cfg", "w", encoding="utf-8"):
            ...

    if not os.path.exists("configs/auto_delivery.cfg"):
        with open("configs/auto_delivery.cfg", "w", encoding="utf-8"):
            ...


def create_config_obj(settings) -> ConfigParser:
    """
    Создает объект конфига с нужными настройками.

    :param settings: dict настроек.

    :return: объект конфига.
    """
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    config.read_dict(settings)
    return config


def contains_russian(text: str) -> bool:
    for char in text:
        if 'А' <= char <= 'я' or char in 'Ёё':
            return True
    return False

def input_proxy(set_telebot_proxy: bool = False) -> str | None:
    while True:
        proxy_input = setup_input("Прокси или Enter, чтобы пропустить")

        if not proxy_input:
            if set_telebot_proxy:
                telebot.apihelper.proxy = None
            return None

        try:
            scheme, login, password, ip, port = validate_proxy(proxy_input)
            proxy = build_proxy(scheme, login, password, ip, port)

            if not check_proxy({"http": proxy, "https": proxy}):
                setup_error("не удалось подключиться через указанный прокси. Проверьте адрес и повторите ввод")
                continue

            if set_telebot_proxy:
                telebot.apihelper.proxy = {"http": proxy, "https": proxy}

            return proxy

        except Exception as ex:
            setup_error(f"неверный формат прокси: {ex}")

def setup_telegram_proxy():
    config = load_main_config("configs/_main.cfg")
    print(
        f"\n{ORANGE}{Style.BRIGHT}Настройка прокси Telegram{Style.RESET_ALL}\n"
        f"{Fore.WHITE}Формат: scheme://login:password@ip:port или ip:port. "
        f"Нажмите Enter, если прокси не нужен.{Style.RESET_ALL}")
    while True:
        try:
            proxy = input_proxy(set_telebot_proxy=True)
            username = telebot.TeleBot(config["Telegram"]["token"]).get_me().username
            print(f"{Fore.GREEN}Telegram подключён: @{username}{Style.RESET_ALL}")
            break
        except Exception as ex:
            setup_error(f"Telegram недоступен через этот прокси: {ex}")

    config.set("Telegram", "proxy", proxy or "")
    print(f"{Fore.GREEN}Настройки сохранены.{Style.RESET_ALL}")
    with open("configs/_main.cfg", "w", encoding="utf-8") as f:
        config.write(f)
    time.sleep(5)


def first_setup():
    config = create_config_obj(default_config)
    print(f"\n{ORANGE}{Style.BRIGHT}Первичная настройка PLATA{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Основной конфигурационный файл не найден. "
          f"Пройдите пять шагов, чтобы подключить FunPay и Telegram.{Style.RESET_ALL}")

    while True:
        setup_step(1, "Подключение FunPay",
                   "Введите golden_key вашего FunPay-аккаунта. Это значение cookie golden_key на сайте funpay.com.")
        golden_key = setup_input("golden_key")
        if len(golden_key) != 32:
            setup_error("golden_key должен содержать 32 символа")
            continue
        config.set("FunPay", "golden_key", golden_key)
        break

    while True:
        setup_step(2, "User-Agent",
                   "Можно указать User-Agent браузера. Нажмите Enter, чтобы использовать безопасное значение по умолчанию.")
        user_agent = setup_input("User-Agent или Enter")
        if contains_russian(user_agent):
            setup_error("User-Agent не должен содержать кириллицу")
            continue
        if user_agent:
            config.set("FunPay", "user_agent", user_agent)
        break

    setup_step(3, "Telegram-бот",
               "Сначала укажите прокси для Telegram, если он необходим. Формат: scheme://login:password@ip:port.")
    proxy = input_proxy(set_telebot_proxy=True)

    if proxy:
        config.set("Telegram", "proxy", proxy)


    while True:
        print(
            f"\n{Fore.WHITE}Создайте бота через @BotFather и вставьте полученный API-токен.{Style.RESET_ALL}")
        token = setup_input("Telegram Bot Token")
        try:
            if not token or not token.split(":")[0].isdigit():
                raise Exception("Неправильный формат токена")
            username = telebot.TeleBot(token).get_me().username
            print(f"{Fore.GREEN}Telegram-бот подключён: @{username}{Style.RESET_ALL}")
        except Exception as ex:
            s = ""
            if str(ex):
                s = f" ({str(ex)})"
            setup_error(f"не удалось подключить Telegram-бота{s}")
            continue
        break

    while True:
        print(
            f"\n{ORANGE}{Style.BRIGHT}[Шаг 4/5] Пароль панели{Style.RESET_ALL}\n"
            f"{Fore.WHITE}Минимум 8 символов: строчная и заглавная буквы, а также цифра.{Style.RESET_ALL}")
        password = setup_input("Пароль")
        if len(password) < 8 or password.lower() == password or password.upper() == password or not any(
                [i.isdigit() for i in password]):
            setup_error("пароль не соответствует требованиям")
            continue
        break

    config.set("Telegram", "enabled", "1")
    config.set("Telegram", "token", token)
    config.set("Telegram", "secretKeyHash", hash_password(password))

    setup_step(5, "Прокси FunPay",
               "Укажите прокси для запросов к FunPay или нажмите Enter, если прокси не нужен.")
    proxy = input_proxy(set_telebot_proxy=False)

    if proxy:
        config.set("Proxy", "proxy", proxy)
        config.set("Proxy", "enable", "1")
        config.set("Proxy", "check", "1")

    print(f"\n{Fore.GREEN}{Style.BRIGHT}Настройка PLATA завершена.{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Конфигурация сохранена. Перезапустите PLATA, откройте своего Telegram-бота "
          f"и отправьте команду /start или /menu.{Style.RESET_ALL}")
    with open("configs/_main.cfg", "w", encoding="utf-8") as f:
        config.write(f)
    time.sleep(10)
