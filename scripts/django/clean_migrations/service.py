import os
from pathlib import Path

from custom_python_logger import get_logger

logger = get_logger(__name__)

IGNORED_DIRS: list[str] = [".venv"]
IGNORED_FILES: list[str] = ["__init__.py"]


def clean_migrations_folders(root_dir: Path) -> None:
    """Recursively delete all migration files under root_dir.

    Skips __init__.py files and directories listed in IGNORED_DIRS.

    Args:
        root_dir: The directory to search for migrations folders.
    """
    for dirpath, dirnames, _ in os.walk(root_dir):
        if any(ignored in dirpath for ignored in IGNORED_DIRS):
            continue

        if "migrations" in dirnames:
            migrations_dir = Path(dirpath) / "migrations"
            logger.info("Cleaning: %s", migrations_dir)

            for filename in os.listdir(migrations_dir):
                file_path = migrations_dir / filename
                if filename in IGNORED_FILES and file_path.is_file():
                    continue
                try:
                    os.remove(file_path)
                    logger.info("Deleted: %s", file_path)
                except Exception:
                    logger.exception("Failed to delete: %s", file_path)
