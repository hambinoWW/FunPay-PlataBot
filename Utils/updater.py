"""
Проверка на обновления.
"""
import time
from logging import getLogger
from locales.localizer import Localizer
import requests

from plata_identity import UPDATE_REPOSITORY
import os
import zipfile
import hashlib
import json
from datetime import datetime, timezone
import shutil

logger = getLogger("PLATA.update_checker")
localizer = Localizer()
_ = localizer.translate

HEADERS = {
    "accept": "application/vnd.github+json"
}


class Release:
    """
    Класс, описывающий релиз.
    """

    def __init__(self, name: str, description: str, sources_link: str):
        """
        :param name: название релиза.
        :param description: описание релиза (список изменений).
        :param sources_link: ссылка на архив с исходниками.
        """
        self.name = name
        self.description = description
        self.sources_link = sources_link


# Получение данных о новом релизе
def get_tags(current_tag: str) -> list[str] | None:
    """
    Получает все теги с GitHub репозитория.
    :param current_tag: текущий тег.

    :return: список тегов.
    """
    if not UPDATE_REPOSITORY:
        return None
    try:
        page = 1
        json_response: list[dict] = []
        while not any([el.get("name") == current_tag for el in json_response]):
            if page != 1:
                time.sleep(1)
            response = requests.get(f"https://api.github.com/repos/{UPDATE_REPOSITORY}/tags?page={page}",
                                    headers=HEADERS)
            if not response.status_code == 200 or not response.json():
                logger.debug(f"Update status code is {response.status_code}!")
                return None
            else:
                json_response.extend(response.json())
                page += 1
        tags = [i.get("name") for i in json_response]
        return tags or None
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return None


def get_next_tag(tags: list[str], current_tag: str):
    """
    Ищет след. тег после переданного.
    Если не находит текущий тег, возвращает первый.
    Если текущий тег - последний, возвращает None.

    :param tags: список тегов.
    :param current_tag: текущий тег.

    :return: след. тег / первый тег / None
    """
    try:
        curr_index = tags.index(current_tag)
    except ValueError:
        return tags[len(tags) - 1]

    if not curr_index:
        return None
    return tags[curr_index - 1]


def get_releases(from_tag: str) -> list[Release] | None:
    """
    Получает данные о доступных релизах, начиная с тега.

    :param from_tag: тег релиза, с которого начинать поиск.

    :return: данные релизов.
    """
    if not UPDATE_REPOSITORY:
        return None
    try:
        page = 1
        json_response: list[dict] = []
        while not any([el.get("tag_name") == from_tag for el in json_response]):
            if page != 1:
                time.sleep(1)
            response = requests.get(f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases?page={page}",
                                    headers=HEADERS)
            if not response.status_code == 200 or not response.json():
                logger.debug(f"Update status code is {response.status_code}!")
                return None
            else:
                json_response.extend(response.json())
                page += 1
        result = []
        to_append = False
        for el in json_response[::-1]:
            if (name := el.get("tag_name")) == from_tag:
                to_append = True

            if to_append:
                description = el.get("body")
                sources = el.get("zipball_url")
                if "#unskippable" in description:
                    to_append = False
                release = Release(name, description, sources)
                result.append(release)
                if not to_append:
                    break
        return result if result else None
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return None


def get_new_releases(current_tag) -> int | list[Release]:
    """
    Проверяет на наличие обновлений.

    :param current_tag: тег текущей версии.

    :return: список объектов релизов или код ошибки:
        1 - произошла ошибка при получении списка тегов.
        2 - текущий тег является последним.
        3 - не удалось получить данные о релизе.
    """
    tags = get_tags(current_tag)
    if tags is None:
        return 1

    next_tag = get_next_tag(tags, current_tag)
    if next_tag is None:
        return 2

    releases = get_releases(next_tag)
    if releases is None:
        return 3
    return releases


#  Загрузка нового релиза
def download_zip(url: str, expected_sha256: str | None = None) -> int:
    """
    Загружает zip архив с обновлением в файл storage/cache/update.zip.

    :param url: ссылка на zip архив.

    :return: 0, если архив с обновлением загружен, иначе - 1.
    """
    try:
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open("storage/cache/update.zip", 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    digest.update(chunk)
        if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
            os.remove("storage/cache/update.zip")
            logger.error("Update archive checksum mismatch")
            return 1
        return 0
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return 1


def _safe_extract(zip_path: str, destination: str) -> None:
    root = os.path.realpath(destination)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = os.path.realpath(os.path.join(destination, member.filename))
            if target != root and not target.startswith(root + os.sep):
                raise ValueError(f"Unsafe archive path: {member.filename}")
        archive.extractall(destination)


def extract_update_archive() -> str | int:
    """
    Разархивирует скачанный update.zip.

    :return: название папки с обновлением (storage/cache/update/<папка с обновлением>) или 1, если произошла ошибка.
    """
    try:
        if os.path.exists("storage/cache/update/"):
            shutil.rmtree("storage/cache/update/", ignore_errors=True)
        os.makedirs("storage/cache/update")

        with zipfile.ZipFile("storage/cache/update.zip", "r") as zip:
            folder_name = zip.filelist[0].filename
        _safe_extract("storage/cache/update.zip", "storage/cache/update/")
        return folder_name
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return 1


def zipdir(path, zip_obj, excluded_paths: tuple[str, ...] = ()):
    """
    Рекурсивно архивирует папку.

    :param path: путь до папки.
    :param zip_obj: объект zip архива.
    """
    for root, dirs, files in os.walk(path):
        if os.path.basename(root) == "__pycache__":
            continue
        normalized_root = os.path.normpath(root)
        if any(normalized_root == os.path.normpath(item) or
               normalized_root.startswith(os.path.normpath(item) + os.sep)
               for item in excluded_paths):
            continue
        for file in files:
            zip_obj.write(os.path.join(root, file),
                          os.path.relpath(os.path.join(root, file),
                                          os.path.join(path, '..')))


def create_backup() -> int:
    """
    Создает резервную копию с папками storage и configs.

    :return: 0, если бэкап создан успешно, иначе - 1.
    """
    try:
        temp_path = "backup.tmp.zip"
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zip:
            zipdir("storage", zip, ("storage/cache/update", "storage/cache/backup"))
            zipdir("configs", zip)
            zipdir("plugins", zip)
            account_count = 0
            try:
                with open("configs/accounts.json", "r", encoding="utf-8") as file:
                    account_count = len(json.load(file).get("accounts", []))
            except (OSError, ValueError, TypeError):
                pass
            zip.writestr("plata-backup.json", json.dumps({
                "product": "PLATA",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "accounts": account_count,
                "schema": 1,
            }, ensure_ascii=False, indent=2))
        os.replace(temp_path, "backup.zip")
        return 0
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return 1


def extract_backup_archive() -> bool:
    """
    Разархивирует скачанный backup.zip. в storage/cache/backup/

    :return: True, если разархивировано. False в случае ошибок.
    """
    try:
        if os.path.exists("storage/cache/backup/"):
            shutil.rmtree("storage/cache/backup/", ignore_errors=True)
        os.makedirs("storage/cache/backup")

        _safe_extract("storage/cache/backup.zip", "storage/cache/backup/")
        return True
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return False


def install_release(folder_name: str) -> int:
    """
    Устанавливает обновление.

    :param folder_name: название папки со скачанным обновлением в storage/cache/update
    :return: 0, если обновление установлено.
        1 - произошла непредвиденная ошибка.
        2 - папка с обновлением отсутствует.
    """
    try:
        release_folder = os.path.join("storage/cache/update", folder_name)
        if not os.path.exists(release_folder):
            return 2

        if os.path.exists(os.path.join(release_folder, "delete.json")):
            with open(os.path.join(release_folder, "delete.json"), "r", encoding="utf-8") as f:
                data = json.loads(f.read())
                for i in data:
                    if not os.path.exists(i):
                        continue
                    if os.path.isfile(i):
                        os.remove(i)
                    else:
                        shutil.rmtree(i, ignore_errors=True)

        for i in os.listdir(release_folder):
            if i == "delete.json":
                continue

            source = os.path.join(release_folder, i)
            if source.endswith(".exe"):
                if not os.path.exists("update"):
                    os.mkdir("update")
                shutil.copy2(source, os.path.join("update", i))
                continue

            if os.path.isfile(source):
                shutil.copy2(source, i)
            else:
                shutil.copytree(source, os.path.join(".", i), dirs_exist_ok=True)
        return 0
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return 1


def install_backup() -> bool:
    """
    Устанавливает бэкап.
    """
    try:
        backup_folder = "storage/cache/backup"
        if not os.path.exists(backup_folder):
            return False

        manifest_path = os.path.join(backup_folder, "plata-backup.json")
        if not os.path.isfile(manifest_path):
            logger.error("Backup manifest is missing")
            return False
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        if not isinstance(manifest, dict) or manifest.get("product") != "PLATA" or manifest.get("schema") != 1:
            logger.error("Unsupported PLATA backup manifest")
            return False

        # Snapshot current user data before any restore, allowing recovery if
        # installation is interrupted.
        safety_backup = "storage/cache/pre_restore_backup.zip"
        with zipfile.ZipFile(safety_backup, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_root in ("configs", "storage", "plugins"):
                if os.path.isdir(source_root):
                    zipdir(source_root, archive, ("storage/cache/update", "storage/cache/backup",
                                                  "storage/cache/pre_restore_backup.zip"))
        root = os.path.realpath(backup_folder)
        destination_root = os.path.realpath(".")
        allowed_roots = {"configs", "storage", "plugins", "plata-backup.json"}
        for i in os.listdir(backup_folder):
            if i not in allowed_roots:
                logger.warning("Skipping unsupported backup entry: %s", i)
                continue
            source = os.path.realpath(os.path.join(backup_folder, i))
            if source != root and not source.startswith(root + os.sep):
                raise ValueError("Unsafe backup source path")
            target = os.path.realpath(os.path.join(destination_root, i))
            if target != destination_root and not target.startswith(destination_root + os.sep):
                raise ValueError(f"Unsafe backup path: {i}")

            if os.path.isfile(source):
                shutil.copy2(source, target)
            else:
                shutil.copytree(source, target, dirs_exist_ok=True)
        return True
    except:
        logger.debug("TRACEBACK", exc_info=True)
        return False
