# pylint: disable=W0212  # legacy data is written past the guards with _base_manager
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from django_versioned_models.models import Release
from tests.testapp.models import Category, Part, Tag

BASE = {"status": "draft", "active": True}


def _fixture(tmp_path: Path, objects: list[dict]) -> str:
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(objects))
    return str(path)


def _part(pk: int, release: Release, **fields: object) -> dict:
    return {"model": "testapp.part", "pk": pk, "fields": {"name": "P", "release": release.pk, **BASE, **fields}}


@pytest.mark.django_db
class TestLoaddataGuards:
    def test_overwrite_row_of_locked_release_is_refused(self, tmp_path: Path, release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        release.lock()
        with pytest.raises(ValidationError, match="is locked"):
            call_command("loaddata", _fixture(tmp_path, [_part(part.pk, release, name="OVERWRITTEN")]), verbosity=0)
        assert Part.objects.get(pk=part.pk).name == "A", "The locked row must stay unchanged"

    def test_insert_into_locked_release_is_refused(self, tmp_path: Path, locked_release: Release) -> None:
        with pytest.raises(ValidationError, match="is locked"):
            call_command("loaddata", _fixture(tmp_path, [_part(900, locked_release)]), verbosity=0)
        assert not Part.objects.filter(pk=900).exists(), "Nothing must be inserted"

    def test_move_out_of_locked_release_is_refused(
        self, tmp_path: Path, release: Release, other_release: Release
    ) -> None:
        part = Part.objects.create(name="A", release=release)
        release.lock()
        with pytest.raises(ValidationError, match="is locked"):
            call_command("loaddata", _fixture(tmp_path, [_part(part.pk, other_release)]), verbosity=0)
        assert Part.objects.get(pk=part.pk).release_id == release.pk, "The row must stay in its locked release"

    def test_move_between_unlocked_releases_is_refused(
        self, tmp_path: Path, release: Release, other_release: Release
    ) -> None:
        part = Part.objects.create(name="A", release=release)
        with pytest.raises(ValidationError, match="cannot move between releases"):
            call_command("loaddata", _fixture(tmp_path, [_part(part.pk, other_release)]), verbosity=0)

    def test_cross_release_fk_is_refused(self, tmp_path: Path, release: Release, other_release: Release) -> None:
        foreign = Part.objects.create(name="B", release=other_release)
        with pytest.raises(ValidationError, match="must point to a row in the same release"):
            call_command("loaddata", _fixture(tmp_path, [_part(900, release, parent=foreign.pk)]), verbosity=0)
        assert not Part.objects.filter(pk=900).exists(), "Nothing must be inserted"

    def test_unlocking_deployed_release_is_refused(self, tmp_path: Path, deployed_release: Release) -> None:
        fields = {f: getattr(deployed_release, f) for f in ("version", "description", "deployed", "is_deprecated")}
        fields.update({"is_locked": False, "created_at": deployed_release.created_at.isoformat()})
        fixture = [{"model": "django_versioned_models.release", "pk": deployed_release.pk, "fields": fields}]
        with pytest.raises(ValidationError, match="is deployed"):
            call_command("loaddata", _fixture(tmp_path, fixture), verbosity=0)
        assert Release.objects.get(pk=deployed_release.pk).is_locked is True, "The deployed release must stay locked"

    def test_loading_into_unlocked_release_succeeds(self, tmp_path: Path, release: Release) -> None:
        tag = Tag.objects.create(name="T", release=release)
        parent = Part.objects.create(name="Parent", release=release)
        call_command(
            "loaddata", _fixture(tmp_path, [_part(900, release, parent=parent.pk, tags=[tag.pk])]), verbosity=0
        )
        loaded = Part.objects.get(pk=900)
        assert (loaded.parent_id, list(loaded.tags.all())) == (parent.pk, [tag]), "A clean fixture must load"


def _snapshot() -> list[tuple]:
    rows = [("release", r.pk, r.version, r.is_locked, r.deployed) for r in Release.objects.order_by("pk")]
    rows += [("category", c.pk, c.name, c.release_id) for c in Category._base_manager.order_by("pk")]
    rows += [("tag", t.pk, t.name, t.release_id) for t in Tag._base_manager.order_by("pk")]
    rows += [
        ("part", p.pk, p.name, p.release_id, p.parent_id, tuple(p.tags.order_by("pk").values_list("pk", flat=True)))
        for p in Part._base_manager.order_by("pk")
    ]
    return rows


# transaction=True: the tests wipe the database with flush, which PostgreSQL refuses inside a transaction
# that still has deferred FK checks pending.
@pytest.mark.django_db(transaction=True)
class TestRestoreReleases:
    @pytest.fixture
    def dump(self, tmp_path: Path, db: None) -> tuple[str, list[tuple]]:
        """A dump of a deployed and an open release, each with a tree and links."""
        shipped, draft = Release.objects.create(version="v-shipped"), Release.objects.create(version="v-draft")
        for rel in (shipped, draft):
            tag = Tag.objects.create(name=f"T-{rel.version}", release=rel)
            parent = Part.objects.create(name=f"Parent-{rel.version}", release=rel)
            child = Part.objects.create(name=f"Child-{rel.version}", release=rel, parent=parent)
            child.tags.add(tag)
            Category.objects.create(name=f"C-{rel.version}", release=rel)
        shipped.lock()
        shipped.deploy()
        path = tmp_path / "dump.json"
        with path.open("w") as out:
            call_command("dumpdata", "django_versioned_models", "testapp", stdout=out)
        return str(path), _snapshot()

    @staticmethod
    def _wipe() -> None:
        call_command("flush", interactive=False, inhibit_post_migrate=True, verbosity=0)
        assert not Release.objects.exists(), "The database must be empty"

    def test_plain_loaddata_of_a_dump_with_locked_releases_is_refused(self, dump: tuple[str, list[tuple]]) -> None:
        path, _ = dump
        self._wipe()
        with pytest.raises(ValidationError, match="is locked"):
            call_command("loaddata", path, verbosity=0)
        assert not Part._base_manager.exists(), "Nothing must be loaded"

    def test_restore_brings_everything_back(self, dump: tuple[str, list[tuple]]) -> None:
        path, before = dump
        self._wipe()
        out = StringIO()
        call_command("restore_releases", path, verbosity=0, stdout=out)
        assert "Restored" in out.getvalue(), "The restore must report success"
        assert _snapshot() == before, "Every release, row, reference and link must come back exactly"

    def test_restore_with_cross_release_references_is_rolled_back(
        self, tmp_path: Path, dump: tuple[str, list[tuple]]
    ) -> None:
        path, _ = dump
        objects = json.loads(Path(path).read_text())
        parts = [o for o in objects if o["model"] == "testapp.part"]
        foreign_parent = next(o for o in parts if o["fields"]["release"] != parts[0]["fields"]["release"])
        parts[0]["fields"]["parent"] = foreign_parent["pk"]
        self._wipe()
        with pytest.raises(CommandError, match="nothing was restored"):
            call_command("restore_releases", _fixture(tmp_path, objects), verbosity=0, stdout=StringIO())
        assert not Release.objects.exists() and not Part._base_manager.exists(), "The whole restore must roll back"
