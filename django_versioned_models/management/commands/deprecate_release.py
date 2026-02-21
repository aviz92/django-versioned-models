"""
Management command: deprecate_release

Marks a release as deprecated — hides it from the GUI and API by default.
Data is fully preserved, nothing is deleted. Reversible.

Usage:
    python manage.py deprecate_release --release-version v1.0.0
    python manage.py deprecate_release --release-version v1.0.0 --undo
"""

from apps.core.models import Release
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Deprecate a release (soft delete — data is preserved)"

    def add_arguments(self, parser):
        parser.add_argument("--release-version", required=True)
        parser.add_argument(
            "--undo",
            action="store_true",
            help="Un-deprecate a previously deprecated release",
        )

    def handle(self, *args, **options):
        version = options["release_version"]

        try:
            release = Release.objects.get(version=version)
        except Release.DoesNotExist:
            raise CommandError(f'Release "{version}" does not exist.')

        if options["undo"]:
            if not release.is_deprecated:
                raise CommandError(f'Release "{version}" is not deprecated.')
            release.undeprecate()
            self.stdout.write(self.style.SUCCESS(f"✅ Release {version} is no longer deprecated."))
        else:
            if release.is_deprecated:
                raise CommandError(f'Release "{version}" is already deprecated.')
            release.deprecate()
            self.stdout.write(
                self.style.SUCCESS(
                    f"🗑️  Release {version} is now deprecated.\n"
                    f"   Data is preserved. To undo: "
                    f"python manage.py deprecate_release --release-version {version} --undo"
                )
            )
