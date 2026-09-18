"""Runtime orchestration for multiple FunPay accounts and one Telegram bot."""

from __future__ import annotations

import copy
import logging
import threading
import html
from pathlib import Path
import time

import Utils.config_loader as cfg_loader
from Utils import plata_tools
import plata_accounts
from plata import Plata
from plata_modules import confirm_reminder


logger = logging.getLogger("PLATA.runtime")


def apply_proxy_to_instance(instance, proxy: str | None) -> None:
    """
    Применяет прокси к запущенному аккаунту без перезапуска.

    :param instance: экземпляр PLATA.
    :param proxy: прокси в формате login:password@ip:port или ip:port, None - отключить прокси.
    """
    normalized = plata_tools.normalize_proxy(proxy)
    proxy_dict = plata_tools.build_proxy_dict(normalized)
    if "Proxy" not in instance.MAIN_CFG:
        instance.MAIN_CFG.add_section("Proxy")
    instance.MAIN_CFG["Proxy"]["enable"] = "1" if normalized else "0"
    instance.MAIN_CFG["Proxy"]["proxy"] = normalized or ""
    instance.proxy = proxy_dict
    account = getattr(instance, "account", None)
    if account is not None:
        account.proxy = proxy_dict or None


class AccountTelegramProxy:
    """Adds account context while forwarding calls to the shared TGBot."""

    def __init__(self, telegram, profile):
        self._telegram = telegram
        self._profile = profile

    def __getattr__(self, name):
        return getattr(self._telegram, name)

    def send_notification(self, text, *args, **kwargs):
        if text:
            label = html.escape(self._profile.name)
            account_id = ("Основной аккаунт" if self._profile.account_id == "primary"
                          else self._profile.account_id)
            text = f"<b>PLATA · {label}</b> <i>{html.escape(account_id)}</i>\n{text}"
        return self._telegram.send_notification(text, *args, **kwargs)


class PlataRuntime:
    def __init__(self, registry, auto_delivery_config, auto_response_config,
                 raw_auto_response_config, version: str):
        self.registry = registry
        self.auto_delivery_config = auto_delivery_config
        self.auto_response_config = auto_response_config
        self.raw_auto_response_config = raw_auto_response_config
        self.version = version
        self.instances: dict[str, Plata] = {}
        self.errors: dict[str, str] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.telegram = None
        self.account_lock = threading.RLock()
        self.health_lock = threading.RLock()
        self.health_checks: set[str] = set()

    def get(self, account_id: str) -> Plata | None:
        return self.instances.get(account_id)

    def active(self) -> Plata | None:
        return self.get(self.registry.active_id())

    def initialize(self) -> "PlataRuntime":
        profiles = [profile for profile in self.registry.list() if profile.enabled]
        if not profiles:
            raise RuntimeError("Нет включённых аккаунтов FunPay")

        active_id = self.registry.active_id()
        profiles.sort(key=lambda profile: profile.account_id != active_id)
        telegram_profiles = [p for p in profiles
                             if cfg_loader.load_main_config(p.config_path)["Telegram"].getboolean("enabled")]
        if telegram_profiles:
            owner = telegram_profiles[0]
            profiles.remove(owner)
            profiles.insert(0, owner)
        for index, profile in enumerate(profiles):
            config = cfg_loader.load_main_config(profile.config_path)
            config = copy.deepcopy(config)
            delivery_path = profile.auto_delivery_path or "configs/auto_delivery.cfg"
            response_path = profile.auto_response_path or "configs/auto_response.cfg"
            products_directory = ("storage/products" if profile.account_id == "primary"
                                  else f"storage/accounts/{profile.account_id}/products")
            if Path(delivery_path).exists():
                delivery_config = cfg_loader.load_auto_delivery_config(delivery_path, products_directory)
            else:
                delivery_config = copy.deepcopy(self.auto_delivery_config)
            if Path(response_path).exists():
                response_config = cfg_loader.load_auto_response_config(response_path)
                raw_response_config = cfg_loader.load_raw_auto_response_config(response_path)
            else:
                response_config = copy.deepcopy(self.auto_response_config)
                raw_response_config = copy.deepcopy(self.raw_auto_response_config)

            # Only the first instance owns Telegram polling. Other accounts use
            # the same TGBot object for event notifications and control.
            telegram_enabled = config["Telegram"].getboolean("enabled")
            if index:
                config["Telegram"]["enabled"] = "0"

            instance = Plata(
                config,
                delivery_config,
                response_config,
                raw_response_config,
                self.version,
            )
            instance.account_registry = self.registry
            instance.account_profile_id = profile.account_id
            instance.runtime = self
            instance.main_config_path = profile.config_path
            instance.auto_delivery_config_path = delivery_path
            instance.auto_response_config_path = response_path
            instance.products_directory = products_directory
            Path(instance.products_directory).mkdir(parents=True, exist_ok=True)
            try:
                instance.init(account_attempts=3)
            except Exception as error:
                with self.account_lock:
                    self.errors[profile.account_id] = str(error)
                logger.error("Не удалось запустить профиль FunPay %s: %s", profile.account_id, error)
                if index == 0 and instance.telegram is not None:
                    self.telegram = instance.telegram
                    self.telegram.runtime = self
                continue

            if index == 0:
                self.telegram = instance.telegram
                if self.telegram is None and telegram_enabled:
                    raise RuntimeError("Не удалось инициализировать Telegram-бота")
                if self.telegram is not None:
                    self.telegram.runtime = self
            if self.telegram is not None:
                instance.telegram = AccountTelegramProxy(self.telegram, profile)

            self.instances[profile.account_id] = instance
            if len(self.instances) == 1:
                Plata.primary_instance = instance
            logger.info("Профиль FunPay успешно запущен: %s", profile.account_id)
        return self

    def run(self) -> None:
        if not self.instances and self.telegram is None:
            logger.error("Не удалось успешно запустить ни одного профиля FunPay.")
            raise RuntimeError("Не удалось запустить службы PLATA")

        for account_id, instance in self.instances.items():
            thread = threading.Thread(
                target=self._run_instance,
                args=(account_id, instance),
                name=f"PLATA-{account_id}",
                daemon=True,
            )
            self.threads[account_id] = thread
            thread.start()

        # Cardinal and Telegram workers are daemon threads. Keep the process
        # alive while allowing KeyboardInterrupt to reach main.py.
        threading.Event().wait()

    def _run_instance(self, account_id: str, instance: Plata) -> None:
        try:
            instance.run()
        except Exception as error:
            with self.account_lock:
                self.errors[account_id] = str(error)
            logger.exception("Работа профиля FunPay остановлена из-за ошибки: %s", account_id)

    def health(self) -> dict[str, dict]:
        result = {}
        for profile in self.registry.list():
            instance = self.instances.get(profile.account_id)
            thread = self.threads.get(profile.account_id)
            result[profile.account_id] = {
                "name": profile.name,
                "enabled": profile.enabled,
                "running": bool(instance and instance.running),
                "thread_alive": bool(thread and thread.is_alive()),
                "username": getattr(getattr(instance, "account", None), "username", None),
                "error": self.errors.get(profile.account_id),
                "uptime": int(time.time() - instance.start_time) if instance and instance.running else None,
                "last_event_age": int(time.time() - instance.last_event_time)
                if instance and instance.last_event_time else None,
            }
        return result

    def check_account(self, account_id: str, timeout: float = 8.0) -> tuple[bool, str]:
        """Perform a bounded live FunPay connectivity check."""
        instance = self.get(account_id)
        if instance is None:
            return False, "аккаунт не запущен"
        with self.health_lock:
            if account_id in self.health_checks:
                return False, "проверка уже выполняется"
            self.health_checks.add(account_id)
        result = {}
        def probe():
            try:
                instance.account.get()
                result["ok"] = True
            except Exception as error:
                result["error"] = str(error)
        worker = threading.Thread(target=probe, daemon=True, name=f"PLATA-health-{account_id}")
        try:
            worker.start()
            worker.join(timeout=max(0.5, float(timeout)))
            if worker.is_alive():
                return False, "проверка превысила лимит времени"
            if result.get("ok"):
                with self.account_lock:
                    self.errors.pop(account_id, None)
                return True, "подключение FunPay подтверждено"
            error = result.get("error", "неизвестная ошибка")
            with self.account_lock:
                self.errors[account_id] = error
            return False, error[:160]
        finally:
            with self.health_lock:
                self.health_checks.discard(account_id)

    def select(self, account_id: str) -> Plata:
        with self.account_lock:
            instance = self.get(account_id)
            if instance is None:
                raise KeyError(account_id)
            self.registry.set_active(account_id)
            if self.telegram is not None:
                self.telegram.cardinal = instance
            return instance

    def set_proxy(self, account_id: str, proxy: str | None) -> str | None:
        """
        Записывает прокси аккаунта в его конфиг и применяет его на лету, если аккаунт запущен.

        :param account_id: ID аккаунта.
        :param proxy: прокси в формате login:password@ip:port или ip:port, None - отключить прокси.
        :return: нормализованный прокси или None, если прокси отключен.
        """
        profile = self.registry.get(account_id)
        if profile is None:
            raise KeyError(account_id)
        normalized = plata_accounts.write_account_proxy(profile.config_path, proxy)
        with self.account_lock:
            instance = self.instances.get(account_id)
            if instance is not None:
                apply_proxy_to_instance(instance, normalized)
        logger.info("Прокси аккаунта %s обновлён: %s", account_id, "включён" if normalized else "отключён")
        return normalized

    def sync_proxy_pool(self) -> dict:
        """
        Перечитывает общий список прокси с диска во всех запущенных аккаунтах.

        :return: актуальный список прокси.
        """
        pool = plata_tools.load_proxy_dict()
        with self.account_lock:
            for instance in self.instances.values():
                instance.proxy_dict = pool
        return pool

    def disable(self, account_id: str) -> None:
        with self.account_lock:
            instance = self.instances.pop(account_id, None)
            if instance is not None:
                instance.stop()
            confirm_reminder.stop(account_id)
            self.registry.set_enabled(account_id, False)
            self.errors.pop(account_id, None)
            active = self.active()
            if self.telegram is not None and active is not None:
                self.telegram.cardinal = active

    def enable(self, account_id: str) -> None:
        with self.account_lock:
            self.registry.set_enabled(account_id, True)

    def start_profile(self, profile) -> Plata:
        """Initialize and start one newly added profile without restarting PLATA."""
        with self.account_lock:
            return self._start_profile_locked(profile)

    def _start_profile_locked(self, profile) -> Plata:
        if profile.account_id in self.instances:
            return self.instances[profile.account_id]
        if self.telegram is None:
            raise RuntimeError("Telegram-бот не инициализирован")

        config = copy.deepcopy(cfg_loader.load_main_config(profile.config_path))
        delivery_path = profile.auto_delivery_path or "configs/auto_delivery.cfg"
        response_path = profile.auto_response_path or "configs/auto_response.cfg"
        products_directory = ("storage/products" if profile.account_id == "primary"
                              else f"storage/accounts/{profile.account_id}/products")
        Path(products_directory).mkdir(parents=True, exist_ok=True)
        delivery_config = cfg_loader.load_auto_delivery_config(delivery_path, products_directory)
        response_config = cfg_loader.load_auto_response_config(response_path)
        raw_response_config = cfg_loader.load_raw_auto_response_config(response_path)
        config["Telegram"]["enabled"] = "0"

        instance = Plata(config, delivery_config, response_config, raw_response_config, self.version)
        instance.account_registry = self.registry
        instance.account_profile_id = profile.account_id
        instance.runtime = self
        instance.main_config_path = profile.config_path
        instance.auto_delivery_config_path = delivery_path
        instance.auto_response_config_path = response_path
        instance.products_directory = products_directory
        try:
            instance.init(account_attempts=3)
        except Exception as error:
            self.errors[profile.account_id] = str(error)
            raise
        instance.telegram = AccountTelegramProxy(self.telegram, profile)
        self.instances[profile.account_id] = instance
        self.errors.pop(profile.account_id, None)
        thread = threading.Thread(target=self._run_instance, args=(profile.account_id, instance),
                                  name=f"PLATA-{profile.account_id}", daemon=True)
        self.threads[profile.account_id] = thread
        thread.start()
        return instance

    def restart_profile(self, account_id: str) -> Plata:
        with self.account_lock:
            profile = self.registry.get(account_id)
            if profile is None or not profile.enabled:
                raise KeyError(account_id)
            old_instance = self.instances.pop(account_id, None)
            if old_instance is not None:
                old_instance.stop()
            confirm_reminder.stop(account_id)
            self.threads.pop(account_id, None)
            self.errors.pop(account_id, None)
            instance = self.start_profile(profile)
            if self.registry.active_id() == account_id and self.telegram is not None:
                self.telegram.cardinal = instance
            return instance
