"""Build a clean PLATA archive without user data or secrets."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dist" / "PLATA-0.1.2-public.zip"
FILES = ["main.py", "first_setup.py", "plata_core.py", "plata.py", "plata_identity.py", "plata_accounts.py",
         "plata_runtime.py", "plata_analytics.py", "plata_plugins.py", "handlers.py",
         "requirements.txt", "Start.bat", "Setup.bat", "Dockerfile", "docker-compose.yml", ".dockerignore",
         "PLATA.ico", "PLATA-fox.png", "PLATA@.service", "README.md", "INSTALL.md",
         "PLUGIN_COMPATIBILITY.md"]
DIRS = ["FunPayAPI", "Utils", "tg_bot", "locales", "compatibility", "plata_modules"]


def build() -> Path:
    OUTPUT.parent.mkdir(exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
        for directory in DIRS:
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, str(path.relative_to(ROOT)))
        archive.write(ROOT / "configs" / "_main.example.cfg", "configs/_main.example.cfg")
    return OUTPUT


if __name__ == "__main__":
    print(build())
