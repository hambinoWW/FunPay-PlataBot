import time
from pip._internal.cli.main import main

# todo убрать когда-то

try:
    import lxml
except ModuleNotFoundError:
    main(["install", "-U", "lxml>=5.3.0"])
except:
    pass
try:
    import bcrypt
except ModuleNotFoundError:
    main(["install", "-U", "bcrypt>=4.2.0"])
except:
    pass
try:
    import socks
except ModuleNotFoundError:
    main(["install", "-U", "pysocks>=1.7.1"])
except:
    pass
import Utils.plata_tools as plata_tools
import Utils.config_loader as cfg_loader
from first_setup import first_setup
from colorama import Style
from Utils.logger import adapt_console_colors, configure_logging, refresh_console_support
import logging
import colorama
import sys
import os
from plata import Plata
import Utils.exceptions as excs
from locales.localizer import Localizer
from plata_identity import PRODUCT_NAME, PRODUCT_VERSION
from plata_accounts import AccountRegistry
from plata_runtime import PlataRuntime


VERSION = PRODUCT_VERSION

plata_logo = r"""
██████╗ ██╗      █████╗ ████████╗ █████╗
██╔══██╗██║     ██╔══██╗╚══██╔══╝██╔══██╗
██████╔╝██║     ███████║   ██║   ███████║
██╔═══╝ ██║     ██╔══██║   ██║   ██╔══██║
██║     ███████╗██║  ██║   ██║   ██║  ██║
╚═╝     ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
"""

plata_tools.set_console_title(f"{PRODUCT_NAME} v{VERSION}")

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(__file__))

folders = ["configs", "logs", "storage", "storage/cache", "storage/plugins", "storage/products", "plugins"]
for i in folders:
    if not os.path.exists(i):
        os.makedirs(i)

files = ["configs/auto_delivery.cfg", "configs/auto_response.cfg"]
for i in files:
    if not os.path.exists(i):
        with open(i, "w", encoding="utf-8") as f:
            ...

colorama.init()
refresh_console_support()

configure_logging()
logging.raiseExceptions = False
logger = logging.getLogger("main")
logger.debug("------------------------------------------------------------------")

orange = adapt_console_colors("\033[38;5;208m")
print(f"{orange}{Style.BRIGHT}{plata_logo}{Style.RESET_ALL}")
print(f"{orange}{Style.BRIGHT}PLATA v{VERSION}{Style.RESET_ALL}\n")
info_color = adapt_console_colors("\033[38;5;110m")
print(f"{info_color}{Style.BRIGHT}By hambinO{Style.RESET_ALL}")
print(f"{info_color}{Style.BRIGHT}Платформа автоматизации FunPay{Style.RESET_ALL}")
print(f"{info_color} * Форк FunPay Cardinal, расширенный в рамках PLATA{Style.RESET_ALL}")
print(f"{info_color} * Telegram-панель: {orange}/menu{Style.RESET_ALL}")
print(f"{info_color} * Несколько FunPay-аккаунтов в одной установке{Style.RESET_ALL}")
print(f"{info_color} * Совместимость с плагинами Cardinal{Style.RESET_ALL}")
print(f"{info_color} * Устанавливайте плагины только из доверенных источников{Style.RESET_ALL}")

if not os.path.exists("configs/_main.cfg"):
    first_setup()
    sys.exit()

ACCOUNT_REGISTRY = AccountRegistry()
ACCOUNT_REGISTRY.ensure_legacy_account()

is_service = os.getenv("PLATA_IS_RUNNING_AS_SERVICE", os.getenv("FPC_IS_RUNNIG_AS_SERVICE", "0")) == "1"
if sys.platform == "linux" and is_service:
    import getpass

    pid = str(os.getpid())
    pidFile = open(f"/run/PLATA/{getpass.getuser()}/PLATA.pid", "w")
    pidFile.write(pid)
    pidFile.close()

    logger.info(f"$GREENPID файл создан, PID процесса: {pid}")  # locale


try:
    logger.info("$MAGENTAЗагружаю конфиг _main.cfg...")  # locale
    MAIN_CFG = cfg_loader.load_main_config("configs/_main.cfg")
    localizer = Localizer(MAIN_CFG["Other"]["language"])
    _ = localizer.translate

    logger.info("$MAGENTAЗагружаю конфиг auto_response.cfg...")  # locale
    AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
    RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")

    logger.info("$MAGENTAЗагружаю конфиг auto_delivery.cfg...")  # locale
    AD_CFG = cfg_loader.load_auto_delivery_config("configs/auto_delivery.cfg")
except excs.ConfigParseError as e:
    logger.error(e)
    logger.error("Завершаю программу...")  # locale
    time.sleep(5)
    sys.exit()
except UnicodeDecodeError:
    logger.error("Произошла ошибка при расшифровке UTF-8. Убедитесь, что кодировка файла = UTF-8, "
                 "а формат конца строк = LF.")  # locale
    logger.error("Завершаю программу...")  # locale
    time.sleep(5)
    sys.exit()
except:
    logger.critical("Произошла непредвиденная ошибка.")  # locale
    logger.warning("TRACEBACK", exc_info=True)
    logger.error("Завершаю программу...")  # locale
    time.sleep(5)
    sys.exit()

localizer = Localizer(MAIN_CFG["Other"]["language"])

try:
    PlataRuntime(ACCOUNT_REGISTRY, AD_CFG, AR_CFG, RAW_AR_CFG, VERSION).initialize().run()
except KeyboardInterrupt:
    logger.info("Завершаю программу...")  # locale
    sys.exit()
except:
    logger.critical("При работе PLATA произошла необработанная ошибка.")  # locale
    logger.warning("TRACEBACK", exc_info=True)
    logger.critical("Завершаю программу...")  # locale
    time.sleep(5)
    sys.exit()
