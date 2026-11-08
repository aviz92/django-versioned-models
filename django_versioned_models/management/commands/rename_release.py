"""
Management command: rename_release

Rename a release (change its version string). Data is untouched — versioned
rows reference the release by primary key. Deployed releases cannot be renamed.

Usage:
    python manage.py rename_release --release-version v1.0.0 --new-version v1.0.0-final
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.services import rename_release


class Command(BaseCommand):
    help = "Rename a release (not allowed for deployed releases)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)
        parser.add_argument("--new-version", required=True)

    def handle(self, **kwargs: Any) -> None:
        old_version = kwargs["release_version"]
        try:
            release = rename_release(old_version, kwargs["new_version"])
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(self.style.SUCCESS(f"✏️  Release {old_version} renamed to {release.version}."))
