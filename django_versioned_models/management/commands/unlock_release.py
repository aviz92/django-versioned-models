"""
Management command: unlock_release

Use ONLY for releases that have NOT yet been deployed to production.
Unlocking a release that's already live is dangerous — customers are
relying on that data being frozen.

Usage:
    python manage.py unlock_release --release-version v1.2.0
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.models import Release


class Command(BaseCommand):
    help = "Unlock a release to allow editing (only for unreleased versions)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)

    def handle(self, **kwargs: Any) -> None:
        version = kwargs["release_version"]

        try:
            release = Release.objects.get(version=version)
        except Release.DoesNotExist as exc:
            raise CommandError(f'Release "{version}" does not exist.') from exc

        if not release.is_locked:
            raise CommandError(f'Release "{version}" is not locked.')

        # Safety confirmation
        self.stdout.write(
            self.style.WARNING(
                f"\n⚠️  WARNING: You are about to unlock release {version}.\n"
                f"   Only do this if this version has NOT been deployed to production.\n"
            )
        )
        if input("Type the version name to confirm: ") != version:
            raise CommandError("Confirmation failed. Aborting.")

        release.is_locked = False
        release.locked_at = None
        release.save(update_fields=["is_locked", "locked_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"🔓 Release {version} is now unlocked and editable.\n"
                f"   Remember to lock it again before deploying: "
                f"python manage.py lock_release --release-version {version}"
            )
        )
