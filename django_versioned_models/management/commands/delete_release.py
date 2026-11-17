"""
Management command: delete_release

Permanently delete a release and every versioned row that belongs to it.
Deployed releases cannot be deleted. Releases branched from the deleted one
are kept, but lose their based_on link (a warning lists them).

Usage:
    python manage.py delete_release --release-version v1.2.0
    python manage.py delete_release --release-version v1.2.0 --dry-run
    python manage.py delete_release --release-version v1.2.0 --force
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_versioned_models.services import delete_release, get_child_release_versions


class Command(BaseCommand):
    help = "Delete a release and all its versioned rows (not allowed for deployed releases)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--release-version", required=True)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without deleting anything",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt (for CI/automation — use with caution)",
        )

    def handle(self, **kwargs: Any) -> None:
        version = kwargs["release_version"]

        try:
            planned = delete_release(version, dry_run=True)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Release {version} — objects to delete:\n{self._format_counts(planned)}")

        if children := get_child_release_versions(version):
            self.stdout.write(
                self.style.WARNING(
                    f"\n⚠️  Release {version} is the base of: {', '.join(children)}.\n"
                    f"   They will be kept, but their based_on will be cleared (lineage is lost).\n"
                )
            )

        if kwargs["dry_run"]:
            self.stdout.write(self.style.NOTICE("Dry run — nothing was deleted."))
            return

        if not kwargs["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\n⚠️  WARNING: You are about to permanently delete release {version} and all its rows.\n"
                    f"   This cannot be undone.\n"
                )
            )
            if input("Type the version name to confirm: ").strip() != version:  # noqa: S322
                raise CommandError("Confirmation failed. Aborting.")
        else:
            self.stdout.write(
                self.style.WARNING(f"\n⚠️  WARNING: Deleting release {version} without confirmation (--force).\n")
            )

        try:
            deleted = delete_release(version)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        summary = self._format_counts(deleted)
        self.stdout.write(self.style.SUCCESS(f"🗑️  Release {version} deleted. Removed:\n{summary}"))

    @staticmethod
    def _format_counts(counts: dict[str, int]) -> str:
        return "\n".join(f"   {label}: {count}" for label, count in counts.items())
