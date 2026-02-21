"""
Management command: create_release

Called by CI to create a new release branched from an existing locked one.

Usage:
    python manage.py create_release --version v2.1.0 --based-on v2.0.0
    python manage.py create_release --version v2.1.1 --based-on v2.1.0  # patch

In .gitlab-ci.yml:
    script:
      - python manage.py create_release --version $CI_COMMIT_TAG --based-on $BASE_VERSION
"""

from apps.core.services import create_release
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a new release by copying data from an existing locked release"

    def add_arguments(self, parser):
        parser.add_argument("--release-version", required=True, help="New version, e.g. v2.1.0")
        parser.add_argument("--based-on", required=True, help="Source version to copy from")
        parser.add_argument("--description", default="", help="Release notes")

    def handle(self, *args, **options):
        version = options["release_version"]
        based_on = options["based_on"]
        description = options["description"]

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
                f"   When ready to ship: python manage.py lock_release --version {version}"
            )
        )
