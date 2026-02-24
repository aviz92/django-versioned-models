"""
Management command: lock_release

Called by CI at deployment time to freeze a release.

Usage:
    python manage.py lock_release --version v2.1.0
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.services import lock_release


class Command(BaseCommand):
    help = "Lock a release, making it immutable"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)

    def handle(self, **options: Any) -> None:
        try:
            release = lock_release(options["release_version"])
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(self.style.SUCCESS(f"🔒 Release {release.version} is now locked and immutable."))
