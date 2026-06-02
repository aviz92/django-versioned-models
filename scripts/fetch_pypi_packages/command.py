import argparse
import sys
from typing import Any

from python_base_command import BaseCommand, CommandError

from scripts.fetch_pypi_packages.service import DEFAULT_IGNORE, fetch_user_packages

DEFAULT_USER = "aviz"


class Command(BaseCommand):
    help = "Fetch all PyPI packages for a user and output their latest versions"
    version = "0.0.1"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--user",
            type=str,
            default=DEFAULT_USER,
            help=f"PyPI username to query (default: {DEFAULT_USER})",
        )
        parser.add_argument(
            "--ignore",
            nargs="*",
            default=DEFAULT_IGNORE,
            metavar="PACKAGE",
            help="Packages to ignore (default: %(default)s)",
        )

    def handle(self, **kwargs: Any) -> None:
        user: str = kwargs["user"].strip()
        ignore: list[str] = kwargs["ignore"] or []

        if not user:
            raise CommandError("--user cannot be empty.")

        self.logger.step("Fetching packages for PyPI user: %s", user)

        try:
            results = fetch_user_packages(user=user, ignore=ignore)
        except Exception as exc:
            raise CommandError(f"Failed to fetch packages for user '{user}': {exc}") from exc

        if not results:
            raise CommandError(f"No packages found for PyPI user: '{user}'")

        self.logger.step("Found %d package(s) — pyproject.toml format:", len(results))
        s = "\ndependencies = ["
        for pkg, version in results:
            s += f'\n    "{pkg}>={version}",'
        s+= "\n]"
        self.logger.step(s)


def main(argv: list[str] | None = None) -> None:
    Command().run_from_argv(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    main()
