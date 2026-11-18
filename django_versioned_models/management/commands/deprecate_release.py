"""
Management command: deprecate_release

Marks a release as deprecated — hides it from the GUI and API by default.
Data is fully preserved, nothing is deleted. Reversible.

Usage:
    python manage.py deprecate_release --release-version v1.0.0
    python manage.py deprecate_release --release-version v1.0.0 --undo
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.services import deprecate_release


class Command(BaseCommand):
    help = "Deprecate a release (soft delete — data is preserved)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)
        parser.add_argument(
            "--undo",
            action="store_true",
            help="Un-deprecate a previously deprecated release",
        )

    def handle(self, **kwargs: Any) -> None:
        version = kwargs["release_version"]
        undo = kwargs["undo"]
        try:
            deprecate_release(version, undo=undo)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if undo:
            self.stdout.write(self.style.SUCCESS(f"✅ Release {version} is no longer deprecated."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"🗑️  Release {version} is now deprecated.\n"
                    f"   Data is preserved. To undo: "
                    f"python manage.py deprecate_release --release-version {version} --undo"
                )
            )
