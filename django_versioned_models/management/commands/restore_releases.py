"""
Management command: restore_releases

Load fixtures that contain locked or deployed releases — typically a full dump made with dumpdata.
Plain loaddata refuses to write rows of a locked release, so a restore goes through this command:
it loads with that check lifted, then verifies that no reference crosses releases. If one does,
the whole load is rolled back and nothing is restored.

Usage:
    python manage.py dumpdata django_versioned_models myapp > dump.json
    python manage.py restore_releases dump.json
"""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from django_versioned_models.mixins import allow_raw_load
from django_versioned_models.services import find_cross_release_references

_EXAMPLES = 10


class Command(BaseCommand):
    help = "Load fixtures that contain locked or deployed releases (a full dump), then verify isolation"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("fixtures", nargs="+", help="Fixture files or labels, as for loaddata")

    def handle(self, **kwargs: Any) -> None:
        with transaction.atomic(), allow_raw_load():
            call_command("loaddata", *kwargs["fixtures"], verbosity=kwargs["verbosity"], stdout=self.stdout)
            if found := find_cross_release_references():
                for field, rows in found.items():
                    examples = ", ".join(str(row) for row in rows[:_EXAMPLES])
                    self.stdout.write(self.style.WARNING(f"⚠️  {field}: {len(rows)} — {examples}"))
                raise CommandError(
                    "The fixtures contain references that cross releases — nothing was restored. "
                    "Fix them in the fixtures (or the source database) and restore again."
                )
        self.stdout.write(self.style.SUCCESS("✅ Restored. All releases are isolated."))
