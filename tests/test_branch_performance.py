import pytest
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save

from django_versioned_models import services
from django_versioned_models.mixins import building_release
from django_versioned_models.models import Release
from django_versioned_models.services import create_release
from tests.testapp.models import Category, Product


def _fill(release: Release, categories: int, products: int) -> None:
    cats = Category.objects.bulk_create([Category(name=f"c{i}", release=release) for i in range(categories)])
    Product.objects.bulk_create(
        [Product(name=f"p{i}", release=release, category=cats[i % categories]) for i in range(products)]
    )


@pytest.mark.django_db
class TestBranchQueryCount:
    def test_bulk_copy_query_count_does_not_grow_per_row(
        self, release: Release, django_assert_max_num_queries: object
    ) -> None:
        _fill(release, categories=100, products=2500)
        release.lock()
        with django_assert_max_num_queries(40):  # type: ignore[operator]
            new = create_release("v2.0.0", release.version)
        assert Product.objects.all_rows(new).count() == 2500, "All rows must be copied"
        assert set(Product.objects.all_rows(new).values_list("category__release_id", flat=True)) == {
            new.pk
        }, "FKs must be remapped into the new release"

    def test_row_by_row_copy_skips_per_row_lock_check(
        self, release: Release, monkeypatch: pytest.MonkeyPatch, django_assert_max_num_queries: object
    ) -> None:
        monkeypatch.setattr(services, "_can_bulk_copy", lambda model: False)
        _fill(release, categories=10, products=100)
        release.lock()
        with django_assert_max_num_queries(110 + 30):  # type: ignore[operator]
            create_release("v2.0.0", release.version)


@pytest.mark.django_db
class TestBulkCreateOptOut:
    def test_bulk_copy_skips_save_signals(self, release: Release) -> None:
        Category.objects.create(name="A", release=release)
        release.lock()
        seen: list[str] = []

        def receiver(sender: type, instance: Category, **kwargs: object) -> None:  # pylint: disable=W0613
            seen.append(instance.name)

        post_save.connect(receiver, sender=Category, weak=False)
        try:
            create_release("v2.0.0", release.version)
        finally:
            post_save.disconnect(receiver, sender=Category)
        assert not seen, "Bulk copy must not fire post_save"

    def test_opted_out_model_is_copied_with_save(self, release: Release, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Category, "copy_with_bulk_create", False, raising=False)
        Category.objects.create(name="A", release=release)
        release.lock()
        seen: list[str] = []

        def receiver(sender: type, instance: Category, **kwargs: object) -> None:  # pylint: disable=W0613
            seen.append(instance.name)

        post_save.connect(receiver, sender=Category, weak=False)
        try:
            create_release("v2.0.0", release.version)
        finally:
            post_save.disconnect(receiver, sender=Category)
        assert seen == ["A"], "An opted-out model must be copied with save()"


@pytest.mark.django_db
class TestLockCheckSkipIsScoped:
    def test_other_locked_release_stays_guarded_while_building(self, release: Release, locked_release: Release) -> None:
        with building_release(release.pk), pytest.raises(ValidationError, match="is locked"):
            Category.objects.create(name="Sneaky", release=locked_release)

    def test_guard_is_back_after_create_release(self, release: Release) -> None:
        release.lock()
        new = create_release("v2.0.0", release.version)
        new.lock()
        with pytest.raises(ValidationError, match="is locked"):
            Category.objects.create(name="Late", release=new)
