"""
Management command: create_release

Usage:
    # Standalone release (no source — locked immediately)
    python manage.py create_release --release-version v1.0.0

    # Branch from an existing locked release
    python manage.py create_release --release-version v1.1.0 --based-on v1.0.0

    # Patch
    python manage.py create_release --release-version v1.1.1 --based-on v1.1.0
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from django_versioned_models.models import Release
from django_versioned_models.services import create_release


class Command(BaseCommand):
    help = "Create a new release"

    def add_arguments(self, parser):
        parser.add_argument("--release-version", required=True, help="New version, e.g. v1.0.0")
        parser.add_argument("--based-on", default=None, help="Source version to copy from (optional)")
        parser.add_argument("--description", default="", help="Release notes")

    def handle(self, *args, **options):
        version = options["release_version"]
        based_on = options["based_on"]
        description = options["description"]

        if not based_on:
            # Standalone release — no source, locked immediately
            release = Release.objects.create(
                version=version,
                description=description,
                is_locked=True,
                locked_at=timezone.now(),
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Release {release.version} created and locked.\n"
                    f"   No source — standalone release.\n"
                    f"   Ready to branch from: "
                    f"python manage.py create_release --release-version <new> --based-on {version}"
                )
            )
        else:
            self.stdout.write(f"Creating release {version} from {based_on}...")
            try:
                release = create_release(
                    version=version,
                    based_on_version=based_on,
                    description=description,
                )
            except ValueError as e:
                raise CommandError(str(e))

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Release {release.version} created successfully.\n"
                    f"   Based on: {based_on}\n"
                    f"   Architects can now edit data for this release.\n"
                    f"   When ready to ship: "
                    f"python manage.py lock_release --release-version {version}"
                )
            )
