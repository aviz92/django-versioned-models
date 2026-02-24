"""
Management command: approve_release

Called by CI to approve all DRAFT rows in a release.
FUTURE rows are left untouched — they are not ready yet.
Inactive rows are skipped — they must be reactivated first.

Usage:
    python manage.py approve_release --release-version v1.1.0
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from django_versioned_models.services import get_versioned_models


class Command(BaseCommand):
    help = "Approve all DRAFT rows in a release (CI only). FUTURE and inactive rows are untouched."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)

    def handle(self, **options: Any) -> None:
        version = options["release_version"]

        try:
            release = Release.objects.get(version=version)
        except Release.DoesNotExist as exc:
            raise CommandError(f'Release "{version}" does not exist.') from exc

        total = 0
        for model in get_versioned_models():
            # for_release() filters active=True, so inactive rows are automatically skipped
            rows = model.objects.for_release(release).filter(status=DataStatus.DRAFT)
            count = rows.count()
            rows.update(status=DataStatus.APPROVED)
            if count:
                self.stdout.write(f"  {model.__name__}: {count} rows approved")
            total += count

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ {total} DRAFT rows approved in release {version}.\n"
                f"   FUTURE and inactive rows were left untouched."
            )
        )
