import sys
from pathlib import Path
from typing import Any

from python_base_command import BaseCommand

from scripts.django.clean_migrations.service import clean_migrations_folders


class Command(BaseCommand):
    help = "Recursively delete all Django migration files in the project"
    version = "0.0.1"

    def handle(self, **_kwargs: Any) -> None:
        root_dir = Path(__file__).parent.parent.parent.parent
        self.logger.step("Cleaning migration files under: %s", root_dir)
        clean_migrations_folders(root_dir)
        self.logger.step("Done.")


def main(argv: list[str] | None = None) -> None:
    Command().run_from_argv(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    main()
