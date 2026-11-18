"""
Management command: check_release_isolation

Read-only scan for references that cross releases — a row pointing to a versioned row of another
release. They are refused on write now, but a database written by an earlier version may still
hold some; those rows can't be saved as a whole and their release can't be branched until fixed.

Exits with an error when any are found, so it can gate a CI pipeline.

Usage:
    python manage.py check_release_isolation
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from django_versioned_models.services import find_cross_release_references

_EXAMPLES = 10


class Command(BaseCommand):
    help = "Report references that cross releases (read-only)"

    def handle(self, **kwargs: Any) -> None:  # pylint: disable=W0613
        if not (found := find_cross_release_references()):
            self.stdout.write(self.style.SUCCESS("✅ All releases are isolated — no references cross releases."))
            return

        for field, rows in found.items():
            examples = ", ".join(str(row) for row in rows[:_EXAMPLES])
            more = f" … and {len(rows) - _EXAMPLES} more" if len(rows) > _EXAMPLES else ""
            self.stdout.write(self.style.WARNING(f"⚠️  {field}: {len(rows)} — {examples}{more}"))
        total = sum(len(rows) for rows in found.values())
        raise CommandError(
            f"{total} reference(s) cross releases. Point each one to the row of its own release "
            f"(or clear it) before branching those releases."
        )
