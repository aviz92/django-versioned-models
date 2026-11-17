import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from django_versioned_models.models import Release
from django_versioned_models.services import delete_release
from tests.testapp.models import Category, Part, Supplier


def _freeze(release: Release, deploy: bool) -> None:
    release.lock()
    if deploy:
        release.deploy()


@pytest.mark.django_db
class TestCascadeIntoFrozenRelease:
    @pytest.mark.parametrize("deploy", [False, True], ids=["locked", "deployed"])
    def test_cascade_delete_into_frozen_rows_raises_and_keeps_rows(
        self, release: Release, supplier: Supplier, deploy: bool
    ) -> None:
        part = Part.objects.create(name="Bolt", release=release, supplier=supplier)
        _freeze(release, deploy)
        with pytest.raises(ValidationError, match=f"locked release {release.version}"), transaction.atomic():
            supplier.delete()
        assert Supplier.objects.filter(pk=supplier.pk).exists(), "Supplier must survive a blocked delete"
        assert Part.objects.filter(pk=part.pk).exists(), "Locked row must survive"

    def test_set_null_into_frozen_rows_raises_and_keeps_value(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="Bolt", release=release, backup_supplier=supplier)
        release.lock()
        with pytest.raises(ValidationError, match="backup_supplier, on_delete=SET_NULL"), transaction.atomic():
            supplier.delete()
        assert Part.objects.get(pk=part.pk).backup_supplier_id == supplier.pk, "Locked row must keep its FK"

    def test_queryset_delete_into_frozen_rows_raises(self, release: Release, supplier: Supplier) -> None:
        Part.objects.create(name="Bolt", release=release, supplier=supplier)
        release.lock()
        with pytest.raises(ValidationError, match="locked release"), transaction.atomic():
            Supplier.objects.all().delete()
        assert Supplier.objects.count() == 1, "Nothing must be deleted"

    def test_blocked_delete_rolls_back_earlier_cascades(self, release: Release) -> None:
        free, frozen = Supplier.objects.create(name="Free"), Supplier.objects.create(name="Frozen")
        draft = Release.objects.create(version="v-draft")
        free_part = Part.objects.create(name="Free part", release=draft, supplier=free)
        Part.objects.create(name="Frozen part", release=release, supplier=frozen)
        release.lock()
        with pytest.raises(ValidationError), transaction.atomic():
            Supplier.objects.all().delete()
        assert Part.objects.filter(pk=free_part.pk).exists(), "Cascades of a blocked delete must roll back"

    def test_cascade_into_unlocked_rows_succeeds(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="Bolt", release=release, supplier=supplier)
        supplier.delete()
        assert not Part.objects.filter(pk=part.pk).exists(), "Unlocked rows must still cascade normally"

    def test_set_null_into_unlocked_rows_succeeds(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="Bolt", release=release, backup_supplier=supplier)
        supplier.delete()
        assert Part.objects.get(pk=part.pk).backup_supplier is None, "Unlocked rows must still SET_NULL"

    def test_unreferenced_object_deletes_normally(self, locked_release: Release, supplier: Supplier) -> None:
        supplier.delete()
        assert not Supplier.objects.filter(pk=supplier.pk).exists(), "Unreferenced supplier must delete"


@pytest.mark.django_db
class TestReleaseDeleteWithFrozenRows:
    def test_delete_locked_release_with_rows_raises(self, release: Release, category: Category) -> None:
        release.lock()
        with pytest.raises(ValidationError, match="Category rows of locked release"), transaction.atomic():
            release.delete()
        assert Category.objects.filter(pk=category.pk).exists(), "Rows must survive"

    def test_delete_unlocked_release_with_rows_succeeds(self, release: Release, category: Category) -> None:
        release.delete()
        assert not Category.objects.filter(pk=category.pk).exists(), "Rows of an unlocked release cascade"


@pytest.mark.django_db
class TestDeleteReleaseServiceBypass:
    def test_delete_release_locked_release_with_self_references_succeeds(
        self, release: Release, supplier: Supplier
    ) -> None:
        root = Part.objects.create(name="Root", release=release, supplier=supplier)
        Part.objects.create(name="Child", release=release, parent=root, backup_supplier=supplier)
        release.lock()
        deleted = delete_release(release.version)
        assert deleted["testapp.Part"] == 2, f"Both parts must be deleted, got {deleted}"
        assert Supplier.objects.filter(pk=supplier.pk).exists(), "Non-versioned supplier must survive"

    def test_delete_release_does_not_unlock_other_releases(self, release: Release, supplier: Supplier) -> None:
        other = Release.objects.create(version="v-other")
        Part.objects.create(name="Other", release=other, supplier=supplier)
        other.lock()
        Part.objects.create(name="Mine", release=release, parent=None)
        release.lock()
        delete_release(release.version)
        with pytest.raises(ValidationError, match="locked release v-other"), transaction.atomic():
            supplier.delete()

    def test_guard_is_active_again_after_delete_release(self, release: Release, supplier: Supplier) -> None:
        Part.objects.create(name="Bolt", release=release, supplier=supplier)
        release.lock()
        delete_release(Release.objects.create(version="v-gone").version)
        with pytest.raises(ValidationError, match="locked release"), transaction.atomic():
            supplier.delete()
