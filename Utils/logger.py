"""
В данном модуле написаны форматтеры для логгера.
"""
from colorama import Back, Fore, Style
import logging.handlers
import logging
import ctypes
import atexit
import queue
import os
import re


# Консольная палитра (256 цветов): оттенки фиксированы и не зависят от темы терминала.
COLOR_TIME = "\033[38;5;244m"       # метка времени
COLOR_SEPARATOR = "\033[38;5;208m"  # фирменный оранжевый, разделитель ">"
COLOR_TEXT = "\033[38;5;252m"       # обычный текст сообщения

LOG_COLORS = {
        logging.DEBUG: "\033[38;5;245m",
        logging.INFO: "\033[38;5;114m",
        logging.WARN: "\033[38;5;214m",
        logging.ERROR: "\033[38;5;203m",
        logging.CRITICAL: "\033[48;5;160m\033[38;5;231m"
}

CLI_LOG_FORMAT = f"{COLOR_TIME}[%(asctime)s]{Style.RESET_ALL}"\
                 f"{COLOR_SEPARATOR}>{Style.RESET_ALL} $RESET%(levelname).1s:{COLOR_TEXT} %(message)s{Style.RESET_ALL}"
CLI_TIME_FORMAT = "%d-%m-%Y %H:%M:%S"

# Фоллбек для консолей без 256-цветного ANSI (старые Windows): ближайшие 16-цветные коды.
_FALLBACK_FG = {
    75: Fore.LIGHTBLUE_EX,
    79: Fore.LIGHTCYAN_EX,
    110: Fore.LIGHTBLUE_EX,
    114: Fore.LIGHTGREEN_EX,
    170: Fore.LIGHTMAGENTA_EX,
    203: Fore.LIGHTRED_EX,
    208: Fore.LIGHTYELLOW_EX,
    214: Fore.LIGHTYELLOW_EX,
    231: Fore.LIGHTWHITE_EX,
    244: Fore.LIGHTBLACK_EX,
    245: Fore.LIGHTBLACK_EX,
    252: Fore.WHITE,
    253: Fore.LIGHTWHITE_EX,
}
_FALLBACK_BG = {
    75: Back.BLUE,
    79: Back.CYAN,
    114: Back.GREEN,
    160: Back.RED,
    170: Back.MAGENTA,
    214: Back.YELLOW,
    244: Back.BLACK,
    253: Back.WHITE,
}
SGR_256_RE = re.compile(r"\x1b\[(38|48);5;(\d+)m")
_SUPPORTS_256: bool | None = None


def _detect_console_256_colors() -> bool:
    """
    Проверяет, включен ли в консоли Windows режим VT (он же включает поддержку 256 цветов).

    :return: True, если 256-цветные ANSI-коды дойдут до терминала как есть.
    """
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW("CONOUT$", 0xC0000000, 0x3, None, 3, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return True  # консоли нет (вывод перенаправлен) - цвета в неё все равно не пишутся
        try:
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
                return True
            return bool(mode.value & 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        return True


def console_supports_256_colors() -> bool:
    """
    Определяет, понимает ли текущая консоль 256-цветные ANSI-коды (результат кэшируется).

    На Windows 10+ режим VT включает colorama при init(), поэтому 256 цветов работают и в cmd.
    В старых консолях (Windows 7/8, отключенный VT) colorama переводит ANSI в вызовы Win32 API,
    которые знают только 16 цветов - там используется фоллбек adapt_console_colors().
    """
    global _SUPPORTS_256
    if _SUPPORTS_256 is None:
        _SUPPORTS_256 = _detect_console_256_colors()
    return _SUPPORTS_256


def refresh_console_support() -> None:
    """Сбрасывает кэш определения - вызывать после colorama.init()."""
    global _SUPPORTS_256
    _SUPPORTS_256 = None


def adapt_console_colors(text: str) -> str:
    """
    Переводит 256-цветные коды в ближайшие 16-цветные, если консоль их не понимает.

    :param text: текст с ANSI-кодами палитры.

    :return: текст с кодами, понятными текущей консоли.
    """
    if console_supports_256_colors():
        return text

    def _replace(match: "re.Match[str]") -> str:
        table = _FALLBACK_BG if match.group(1) == "48" else _FALLBACK_FG
        return table.get(int(match.group(2)), "")

    return SGR_256_RE.sub(_replace, text)

FILE_LOG_FORMAT = "[%(asctime)s][%(filename)s][%(lineno)d]> %(levelname).1s: %(message)s"
FILE_TIME_FORMAT = "%d.%m.%y %H:%M:%S"
CLEAR_RE = re.compile(r"(\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))|(\n)|(\r)")

# Палитра тегов, которые встречаются в текстах логов (см. add_colors).
TAG_COLORS = {
    "$YELLOW": "\033[38;5;214m",
    "$CYAN": "\033[38;5;79m",
    "$MAGENTA": "\033[38;5;170m",
    "$BLUE": "\033[38;5;75m",
    "$GREEN": "\033[38;5;114m",
    "$BLACK": "\033[38;5;244m",
    "$WHITE": "\033[38;5;253m",

    "$B_YELLOW": "\033[48;5;214m",
    "$B_CYAN": "\033[48;5;79m",
    "$B_MAGENTA": "\033[48;5;170m",
    "$B_BLUE": "\033[48;5;75m",
    "$B_GREEN": "\033[48;5;114m",
    "$B_BLACK": "\033[48;5;244m",
    "$B_WHITE": "\033[48;5;253m",
}

# Длинные теги идут первыми, иначе $B_YELLOW может разобраться как $B_ + YELLOW.
COLOR_TAG_RE = re.compile("|".join(sorted((re.escape(tag) for tag in (*TAG_COLORS, "$RESET")),
                                          key=len, reverse=True)))


def add_colors(text: str) -> str:
    """
    Заменяет ключевые слова на коды цветов.

    $YELLOW - желтый текст.

    $CYAN - светло-голубой текст.

    $MAGENTA - фиолетовый текст.

    $BLUE - синий текст.

    Все оттенки заданы 256-цветной палитрой, поэтому одинаковы в любой теме терминала.

    :param text: текст.

    :return: цветной текст.
    """
    for tag, color in TAG_COLORS.items():
        if tag in text:
            text = text.replace(tag, color)
    return text


class CLILoggerFormatter(logging.Formatter):
    """
    Форматтер для вывода логов в консоль.
    """
    def __init__(self):
        super(CLILoggerFormatter, self).__init__()

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        msg = add_colors(msg)
        msg = msg.replace("$RESET", COLOR_TEXT)
        record.msg = msg
        record.args = None
        log_format = CLI_LOG_FORMAT.replace("$RESET", Style.RESET_ALL + LOG_COLORS[record.levelno])
        formatter = logging.Formatter(log_format, CLI_TIME_FORMAT)
        return adapt_console_colors(formatter.format(record))


class FileLoggerFormatter(logging.Formatter):
    """
    Форматтер для сохранения логов в файл.
    """
    def __init__(self):
        super(FileLoggerFormatter, self).__init__()

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        msg = CLEAR_RE.sub("", msg)
        msg = COLOR_TAG_RE.sub("", msg)
        record.msg = msg
        record.args = None
        formatter = logging.Formatter(FILE_LOG_FORMAT, FILE_TIME_FORMAT)
        return formatter.format(record)


LOGGER_NAMES = ["main", "FunPayAPI", "PLATA", "TGBot"]
"""Логгеры PLATA, пишущие и в консоль, и в файл лога."""


class _QueueHandler(logging.handlers.QueueHandler):
    """
    QueueHandler, кладущий LogRecord в очередь как есть, без предварительного форматирования.

    Стандартный QueueHandler.prepare() заранее рендерит record в плоскую строку и обнуляет
    exc_info/exc_text - это сделано для multiprocessing, чтобы через очередь шли только
    picklable-данные. Очередь тут в пределах одного процесса, поэтому сериализация не нужна,
    а её побочный эффект вреден: exc_info схлопывается в record.msg одной строкой, из-за чего
    FileLoggerFormatter (вырезающий переносы строк из message) заодно съедает и переносы строк
    внутри трейсбека.
    """
    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


def configure_logging() -> logging.handlers.QueueListener:
    """
    Настраивает логирование.

    Реальная запись в консоль и в файл лога выполняется не в потоке вызывающего кода, а в
    отдельном потоке-слушателе (QueueHandler/QueueListener): emit() из любого потока приложения
    лишь кладёт запись в очередь и не блокируется. Без этого все логгеры делят одни и те же
    хэндлеры с общим локом на запись - если запись в файл/консоль подвиснет (медленный диск,
    journald, антивирус и т.п.), это останавливает вообще все потоки бота, а не только логирование.

    :return: запущенный слушатель очереди логов. Останавливать вручную не обязательно - остановка
        (со сбросом накопившихся в очереди записей) зарегистрирована через atexit.
    """
    cli_handler = logging.StreamHandler()
    cli_handler.setLevel(logging.INFO)
    cli_handler.setFormatter(CLILoggerFormatter())
    # TeleBot исторически пишет только в файл лога (внутренние ошибки telebot слишком шумные для консоли).
    cli_handler.addFilter(lambda record: record.name != "TeleBot")

    file_handler = logging.handlers.RotatingFileHandler(
        filename="logs/log.log",
        maxBytes=20 * 1024 * 1024,  # 20 мегабайт в байтах
        backupCount=25,  # Сколько ротаций оставить
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(FileLoggerFormatter())

    log_queue = queue.SimpleQueue()
    queue_handler = _QueueHandler(log_queue)

    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(queue_handler)

    telebot_logger = logging.getLogger("TeleBot")
    telebot_logger.setLevel(logging.ERROR)
    telebot_logger.propagate = False
    telebot_logger.addHandler(queue_handler)

    listener = logging.handlers.QueueListener(log_queue, cli_handler, file_handler, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)
    return listener
