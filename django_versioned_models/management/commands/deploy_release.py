"""
Management command: deploy_release

Marks a release as deployed to production.
Deployed releases cannot be unlocked — create a patch release instead.

Usage:
    python manage.py deploy_release --release-version v1.1.0
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.models import Release


class Command(BaseCommand):
    help = "Mark a release as deployed to production (blocks future unlocks)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)

    def handle(self, **kwargs: Any) -> None:
        version = kwargs["release_version"]

        try:
            release = Release.objects.get(version=version)
        except Release.DoesNotExist as exc:
            raise CommandError(f'Release "{version}" does not exist.') from exc

        if release.deployed:
            raise CommandError(f'Release "{version}" is already deployed.')

        try:
            release.deploy()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"🚀 Release {version} is now marked as deployed.\n"
                f"   This release can no longer be unlocked.\n"
                f"   To make changes: python manage.py create_release --release-version <new> --based-on {version}"
            )
        )
