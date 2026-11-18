"""
Management command: approve_release

Called by CI to approve all DRAFT rows in a release.
Must run BEFORE lock_release — locked and deployed releases are immutable.
FUTURE_DEVELOPMENT and FUTURE_DEPRECATION rows are left untouched — they are not ready yet.
Inactive rows are skipped — they must be reactivated first.

Usage:
    python manage.py approve_release --release-version v1.1.0
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.services import approve_release


class Command(BaseCommand):
    help = (
        "Approve all DRAFT rows in a release (CI only). "
        "FUTURE_DEVELOPMENT, FUTURE_DEPRECATION, and inactive rows are untouched."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)

    def handle(self, **kwargs: Any) -> None:
        version = kwargs["release_version"]
        try:
            approved = approve_release(version)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        for label, count in approved.items():
            self.stdout.write(f"  {label.rsplit('.', 1)[-1]}: {count} rows approved")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ {sum(approved.values())} DRAFT rows approved in release {version}.\n"
                f"   FUTURE_DEVELOPMENT, FUTURE_DEPRECATION, and inactive rows were left untouched."
            )
        )
