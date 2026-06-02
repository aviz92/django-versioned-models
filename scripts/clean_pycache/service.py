import os
import shutil
from pathlib import Path

from custom_python_logger import get_logger

logger = get_logger(__name__)

IGNORED_DIRS: list[str] = [".venv"]


def delete_pycache_folders(root_dir: Path) -> None:
    """Recursively delete all __pycache__ folders under root_dir.

    Args:
        root_dir: The directory to search for __pycache__ folders.
    """
    for dirpath, dirnames, _ in os.walk(root_dir):
        if any(ignored in dirpath for ignored in IGNORED_DIRS):
            continue

        if "__pycache__" in dirnames:
            pycache_dir = Path(dirpath) / "__pycache__"
            logger.info("Cleaning: %s", pycache_dir)
            try:
                shutil.rmtree(pycache_dir)
                logger.info("Deleted: %s", pycache_dir)
            except Exception:
                logger.exception("Failed to delete: %s", pycache_dir)
