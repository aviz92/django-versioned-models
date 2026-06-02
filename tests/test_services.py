import pytest

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from django_versioned_models.services import (
    create_release,
    get_versioned_models,
    get_versioned_models_ordered,
    lock_release,
)
from tests.testapp.models import Category, Product


@pytest.mark.django_db
class TestGetVersionedModels:
    def test_returns_concrete_versioned_subclasses(self) -> None:
        models = get_versioned_models()
        assert Category in models, "Category must be discovered"
        assert Product in models, "Product must be discovered"

    def test_excludes_abstract_base(self) -> None:
        from django_versioned_models.mixins import VersionedModel

        models = get_versioned_models()
        assert VersionedModel not in models, "Abstract VersionedModel base must not appear"

    def test_excludes_non_versioned_models(self) -> None:
        models = get_versioned_models()
        assert Release not in models, "Release is not a VersionedModel — must not appear"


@pytest.mark.django_db
class TestGetVersionedModelsOrdered:
    def test_parent_comes_before_child(self) -> None:
        ordered = get_versioned_models_ordered()
        cat_idx = ordered.index(Category)
        prod_idx = ordered.index(Product)
        assert cat_idx < prod_idx, "Category (parent) must come before Product (child with FK)"

    def test_all_models_included(self) -> None:
        ordered = get_versioned_models_ordered()
        assert Category in ordered, "Category must be in ordered list"
        assert Product in ordered, "Product must be in ordered list"


@pytest.mark.django_db
class TestCreateRelease:
    def test_raises_when_source_release_does_not_exist(self, db) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            create_release(version="v2.0.0", based_on_version="nonexistent")

    def test_raises_when_source_release_is_not_locked(self, release: Release) -> None:
        with pytest.raises(ValueError, match="not locked"):
            create_release(version="v2.0.0", based_on_version=release.version)

    def test_new_release_is_unlocked(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        assert new.is_locked is False, "Newly branched release must be unlocked"

    def test_new_release_has_correct_based_on(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        assert new.based_on == locked_release_with_data, "based_on must point to source release"

    def test_new_release_stores_description(self, locked_release_with_data: Release) -> None:
        new = create_release(
            version="v3.0.0",
            based_on_version=locked_release_with_data.version,
            description="Patch release",
        )
        assert new.description == "Patch release", "description must be stored"

    def test_new_release_stores_user_id(self, locked_release_with_data: Release, db) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(username="ci_bot", password="x")
        new = create_release(
            version="v3.0.0",
            based_on_version=locked_release_with_data.version,
            user_id=user.pk,
        )
        assert new.created_by_id == user.pk, "user_id must be stored as created_by_id"

    def test_copies_active_rows(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        source_active = Category.objects.all_rows(locked_release_with_data).filter(active=True).count()
        copied_active = Category.objects.all_rows(new).filter(active=True).count()
        assert copied_active == source_active, "All active rows must be copied"

    def test_copies_inactive_rows(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        source_inactive = Category.objects.all_rows(locked_release_with_data).filter(active=False).count()
        copied_inactive = Category.objects.all_rows(new).filter(active=False).count()
        assert copied_inactive == source_inactive, "Inactive rows must also be copied"

    def test_copies_all_row_count(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        source_count = Category.objects.all_rows(locked_release_with_data).count()
        new_count = Category.objects.all_rows(new).count()
        assert new_count == source_count, "Total row count must match after copy"

    def test_remaps_fk_relationships(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        new_products = Product.objects.all_rows(new).select_related("category")
        new_category_ids = set(Category.objects.all_rows(new).values_list("pk", flat=True))
        for product in new_products:
            if product.category_id is not None:
                assert (
                    product.category_id in new_category_ids
                ), f"Product '{product.name}' FK must point to new release's category, not source"

    def test_preserves_row_status(self, locked_release_with_data: Release) -> None:
        new = create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)
        source_approved = Category.objects.all_rows(locked_release_with_data).filter(status=DataStatus.APPROVED).count()
        new_approved = Category.objects.all_rows(new).filter(status=DataStatus.APPROVED).count()
        assert new_approved == source_approved, "Row statuses must be preserved in the copy"

    def test_is_atomic_rolls_back_on_error(self, locked_release_with_data: Release) -> None:
        from unittest.mock import patch

        release_count_before = Release.objects.count()
        with patch(
            "django_versioned_models.services._copy_model_rows",
            side_effect=RuntimeError("forced failure"),
        ):
            with pytest.raises(RuntimeError, match="forced failure"):
                create_release(version="v3.0.0", based_on_version=locked_release_with_data.version)

        assert (
            Release.objects.count() == release_count_before
        ), "Transaction must roll back — no new release must be persisted on error"


@pytest.mark.django_db
class TestLockRelease:
    def test_lock_release_succeeds(self, release: Release) -> None:
        locked = lock_release(release.version)
        locked.refresh_from_db()
        assert locked.is_locked is True, "lock_release() must lock the release"

    def test_lock_release_sets_locked_at(self, release: Release) -> None:
        locked = lock_release(release.version)
        locked.refresh_from_db()
        assert locked.locked_at is not None, "locked_at must be set by lock_release()"

    def test_lock_release_not_found_raises(self, db) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            lock_release("nonexistent-version")

    def test_lock_release_already_locked_raises(self, locked_release: Release) -> None:
        with pytest.raises(ValueError, match="already locked"):
            lock_release(locked_release.version)
