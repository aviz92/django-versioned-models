"""
Management command: approve_release

Called by CI to approve all DRAFT rows in a release.
FUTURE rows are left untouched — they are not ready yet.

Usage:
    python manage.py approve_release --release-version v1.1.0
"""

from apps.core.mixins import DataStatus
from apps.core.models import Release
from apps.core.services import get_versioned_models
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Approve all DRAFT rows in a release (CI only). FUTURE rows are untouched."

    def add_arguments(self, parser):
        parser.add_argument("--release-version", required=True)

    def handle(self, *args, **options):
        version = options["release_version"]

        try:
            release = Release.objects.get(version=version)
        except Release.DoesNotExist:
            raise CommandError(f'Release "{version}" does not exist.')

        total = 0
        for model in get_versioned_models():
            rows = model.objects.for_release(release).filter(status=DataStatus.DRAFT)
            count = rows.count()
            rows.update(status=DataStatus.APPROVED)
            if count:
                self.stdout.write(f"  {model.__name__}: {count} rows approved")
            total += count

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ {total} DRAFT rows approved in release {version}.\n" f"   FUTURE rows were left untouched."
            )
        )
