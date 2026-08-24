# Установка PLATA

## Windows

1. Установите Python 3.11+ с опцией `Add Python to PATH`.
2. Распакуйте релиз PLATA в отдельную папку.
3. Выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Start.bat
```

4. Укажите FunPay golden key, Telegram Bot Token и пароль панели.

## Linux

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Для постоянного запуска используйте `PLATA@.service`.

## Безопасность

Не публикуйте `configs/`, `storage/`, `logs/` и рабочую папку `plugins/`.
Никому не передавайте Telegram Bot Token или FunPay golden key. Автообновление
из внешнего репозитория отключено: устанавливайте только проверенные релизы.
