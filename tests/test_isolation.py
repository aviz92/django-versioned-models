# pylint: disable=W0212  # legacy data is written past the guards with _base_manager
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from django_versioned_models.models import Release
from django_versioned_models.services import find_cross_release_references
from tests.testapp.models import Category, Kit, KitPart, Part, PartSpec, Product, Supplier, Tag


@pytest.mark.django_db
class TestForeignKeyIsolation:
    def test_save_fk_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        part.parent = Part.objects.create(name="B", release=other_release)
        with pytest.raises(ValidationError, match="must point to a row in the same release"):
            part.save()
        assert Part.objects.get(pk=part.pk).parent_id is None, "The cross-release FK must not be stored"

    def test_create_with_fk_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        with pytest.raises(ValidationError, match="Product.category"):
            Product.objects.create(
                name="P", release=release, category=Category.objects.create(name="C", release=other_release)
            )

    def test_one_to_one_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        with pytest.raises(ValidationError, match="PartSpec.part"):
            PartSpec.objects.create(part=Part.objects.create(name="A", release=other_release), release=release)

    def test_versioned_through_row_across_releases_raises(self, release: Release, other_release: Release) -> None:
        kit = Kit.objects.create(name="K", release=release)
        with pytest.raises(ValidationError, match="KitPart.part"):
            KitPart.objects.create(kit=kit, part=Part.objects.create(name="A", release=other_release), release=release)

    def test_same_release_fk_succeeds(self, release: Release) -> None:
        parent = Part.objects.create(name="Parent", release=release)
        child = Part.objects.create(name="Child", release=release, parent=parent)
        assert child.parent_id == parent.pk, "FK inside one release must be allowed"

    def test_fk_to_non_versioned_model_is_not_checked(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="A", release=release, supplier=supplier)
        assert part.supplier_id == supplier.pk, "Shared non-versioned models stay allowed"

    def test_update_fields_without_the_fk_skips_the_check(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        Part._base_manager.filter(pk=part.pk).update(parent=Part.objects.create(name="B", release=other_release))
        part.refresh_from_db()
        part.name = "Renamed"
        part.save(update_fields=["name"])  # legacy cross-release row: other fields stay editable
        with pytest.raises(ValidationError, match="Part.parent"):
            part.save()


@pytest.mark.django_db
class TestQuerySetIsolation:
    def test_queryset_update_fk_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        Part.objects.create(name="A", release=release)
        target = Part.objects.create(name="B", release=other_release)
        with pytest.raises(ValidationError, match="Part.parent"):
            Part.objects.filter(release=release).update(parent=target)

    def test_queryset_update_fk_in_same_release_succeeds(self, release: Release) -> None:
        Part.objects.create(name="A", release=release)
        target = Part.objects.create(name="B", release=release)
        assert Part.objects.filter(release=release, name="A").update(parent=target) == 1, "Same-release update"

    def test_queryset_update_fk_to_none_succeeds(self, release: Release) -> None:
        Part.objects.create(name="A", release=release)
        assert Part.objects.filter(release=release).update(parent=None) == 1, "Clearing an FK is always allowed"

    def test_bulk_create_fk_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        target = Part.objects.create(name="B", release=other_release)
        with pytest.raises(ValidationError, match="Part.parent"):
            Part.objects.bulk_create([Part(name="A", release=release, parent=target)])
        assert not Part.objects.filter(release=release).exists(), "Nothing must be inserted"

    def test_bulk_update_fk_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        part.parent = Part.objects.create(name="B", release=other_release)
        with pytest.raises(ValidationError, match="Part.parent"):
            Part.objects.bulk_update([part], ["parent"])


@pytest.mark.django_db
class TestMovingRowsBetweenReleases:
    def test_save_move_between_unlocked_releases_raises(self, release: Release, other_release: Release) -> None:
        cat = Category.objects.create(name="C", release=release)
        cat.release = other_release
        with pytest.raises(ValidationError, match="cannot move between releases"):
            cat.save()

    def test_queryset_update_release_raises(self, release: Release, other_release: Release) -> None:
        Category.objects.create(name="C", release=release)
        with pytest.raises(ValidationError, match="cannot move between releases"):
            Category.objects.filter(release=release).update(release=other_release)

    def test_bulk_update_release_raises(self, release: Release, other_release: Release) -> None:
        cat = Category.objects.create(name="C", release=release)
        cat.release = other_release
        with pytest.raises(ValidationError, match="cannot move between releases"):
            Category.objects.bulk_update([cat], ["release"])


@pytest.mark.django_db
class TestManyToManyIsolation:
    def test_add_link_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        with pytest.raises(ValidationError, match="Part.tags"), transaction.atomic():
            part.tags.add(Tag.objects.create(name="T", release=other_release))
        assert part.tags.count() == 0, "No link must be created"

    def test_reverse_add_link_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        tag = Tag.objects.create(name="T", release=release)
        with pytest.raises(ValidationError, match="must point to a row in the same release"), transaction.atomic():
            tag.parts.add(Part.objects.create(name="A", release=other_release))

    def test_set_links_to_other_release_raises(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        with pytest.raises(ValidationError, match="Part.tags"), transaction.atomic():
            part.tags.set([Tag.objects.create(name="T", release=other_release)])

    def test_add_link_in_same_release_succeeds(self, release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        part.tags.add(Tag.objects.create(name="T", release=release))
        assert part.tags.count() == 1, "Links inside one release must be allowed"

    def test_link_to_non_versioned_model_is_not_checked(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="A", release=release)
        part.certified_by.add(supplier, through_defaults={"level": "gold"})
        assert part.certified_by.count() == 1, "Links to shared non-versioned models stay allowed"


@pytest.mark.django_db
class TestFindCrossReleaseReferences:
    def test_isolated_database_reports_nothing(self, release: Release, other_release: Release) -> None:
        Part.objects.create(name="A", release=release, parent=Part.objects.create(name="B", release=release))
        Part.objects.create(name="C", release=other_release).tags.add(
            Tag.objects.create(name="T", release=other_release)
        )
        assert not find_cross_release_references(), "Nothing crosses releases"

    def test_legacy_references_are_reported(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        foreign_part, foreign_tag = Part.objects.create(name="B", release=other_release), Tag.objects.create(
            name="T", release=other_release
        )
        Part._base_manager.filter(pk=part.pk).update(parent=foreign_part)
        Part.tags.through.objects.create(part=part, tag=foreign_tag)
        assert find_cross_release_references() == {
            "testapp.Part.parent": [part.pk],
            "testapp.Part.tags": [(part.pk, foreign_tag.pk)],
        }, "Legacy FK and m2m references must be reported"

    def test_command_clean_database_succeeds(self, release: Release) -> None:
        out = StringIO()
        call_command("check_release_isolation", stdout=out)
        assert "All releases are isolated" in out.getvalue(), "Clean database must report success"

    def test_command_legacy_references_raises(self, release: Release, other_release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        Part._base_manager.filter(pk=part.pk).update(parent=Part.objects.create(name="B", release=other_release))
        out = StringIO()
        with pytest.raises(CommandError, match="1 reference"):
            call_command("check_release_isolation", stdout=out)
        assert "testapp.Part.parent: 1" in out.getvalue(), "Command must list the offending field"
