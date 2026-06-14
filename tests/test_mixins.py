import pytest
from django.core.exceptions import ValidationError

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from tests.testapp.models import Category, Product


@pytest.mark.django_db
class TestVersionedManager:
    def test_for_release_returns_active_rows(self, release: Release, category: Category) -> None:
        rows = Category.objects.for_release(release)
        assert category in rows, "for_release must include active rows"

    def test_for_release_excludes_inactive_rows(self, release: Release, category: Category) -> None:
        category.deactivate()
        rows = Category.objects.for_release(release)
        assert category not in rows, "for_release must exclude inactive rows"

    def test_for_release_excludes_other_releases(self, db: None) -> None:
        r1 = Release.objects.create(version="r1")
        r2 = Release.objects.create(version="r2")
        Category.objects.create(name="In R1", release=r1)
        rows = Category.objects.for_release(r2)
        assert rows.count() == 0, "for_release must not return rows from other releases"

    def test_approved_returns_approved_active_rows_only(self, release: Release) -> None:
        draft = Category.objects.create(name="Draft", release=release)
        future = Category.objects.create(name="Future", release=release)
        future.mark_future_development()
        approved = Category.objects.create(name="Approved", release=release)
        approved.approve()

        result = list(Category.objects.approved(release))
        assert approved in result, "approved() must include APPROVED+active rows"
        assert draft not in result, "approved() must exclude DRAFT rows"
        assert future not in result, "approved() must exclude FUTURE_DEVELOPMENT rows"

    def test_approved_excludes_inactive_approved_rows(self, release: Release) -> None:
        cat = Category.objects.create(name="Cat", release=release)
        cat.approve()
        cat.deactivate()
        result = Category.objects.approved(release)
        assert cat not in result, "approved() must exclude inactive rows even if previously approved"

    def test_all_rows_includes_inactive(self, release: Release, category: Category) -> None:
        category.deactivate()
        rows = Category.objects.all_rows(release)
        assert category in rows, "all_rows() must include inactive rows"

    def test_all_rows_excludes_other_releases(self, db: None) -> None:
        r1 = Release.objects.create(version="r1")
        r2 = Release.objects.create(version="r2")
        Category.objects.create(name="In R1", release=r1)
        assert Category.objects.all_rows(r2).count() == 0, "all_rows() must be scoped to the release"


@pytest.mark.django_db
class TestDeactivate:
    def test_deactivate_sets_active_false(self, category: Category) -> None:
        category.deactivate()
        category.refresh_from_db()
        assert category.active is False, "deactivate() must set active=False"

    def test_deactivate_approved_row_resets_status_to_draft(self, category: Category) -> None:
        category.approve()
        category.deactivate()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "deactivate() must reset APPROVED to DRAFT"

    def test_deactivate_draft_row_keeps_draft_status(self, category: Category) -> None:
        assert category.status == DataStatus.DRAFT
        category.deactivate()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "deactivate() must keep DRAFT status as DRAFT"

    def test_deactivate_future_development_row_keeps_status(self, category: Category) -> None:
        category.mark_future_development()
        category.deactivate()
        category.refresh_from_db()
        assert category.status == DataStatus.FUTURE_DEVELOPMENT, "deactivate() must keep FUTURE_DEVELOPMENT status"

    def test_deactivate_already_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="already inactive"):
            category.deactivate()


@pytest.mark.django_db
class TestReactivate:
    def test_reactivate_sets_active_true(self, category: Category) -> None:
        category.deactivate()
        category.reactivate()
        category.refresh_from_db()
        assert category.active is True, "reactivate() must set active=True"

    def test_reactivate_keeps_status_as_draft(self, category: Category) -> None:
        category.deactivate()
        category.reactivate()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "reactivate() must keep status as DRAFT"

    def test_reactivate_already_active_raises(self, category: Category) -> None:
        with pytest.raises(ValidationError, match="already active"):
            category.reactivate()


@pytest.mark.django_db
class TestMarkFutureDevelopment:
    def test_mark_future_development_from_draft_succeeds(self, category: Category) -> None:
        category.mark_future_development()
        category.refresh_from_db()
        assert (
            category.status == DataStatus.FUTURE_DEVELOPMENT
        ), "mark_future_development() must set status to FUTURE_DEVELOPMENT"

    def test_mark_future_development_from_approved_raises(self, category: Category) -> None:
        category.approve()
        with pytest.raises(ValidationError, match="DRAFT"):
            category.mark_future_development()

    def test_mark_future_development_when_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.mark_future_development()


@pytest.mark.django_db
class TestMarkFeatureDeprecation:
    def test_mark_feature_deprecation_from_draft_succeeds(self, category: Category) -> None:
        category.mark_feature_deprecation()
        category.refresh_from_db()
        assert (
            category.status == DataStatus.FEATURE_DEPRECATION
        ), "mark_feature_deprecation() must set status to FEATURE_DEPRECATION"

    def test_mark_feature_deprecation_from_approved_raises(self, category: Category) -> None:
        category.approve()
        with pytest.raises(ValidationError, match="DRAFT"):
            category.mark_feature_deprecation()

    def test_mark_feature_deprecation_when_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.mark_feature_deprecation()


@pytest.mark.django_db
class TestMarkDraft:
    def test_mark_draft_from_future_development_succeeds(self, category: Category) -> None:
        category.mark_future_development()
        category.mark_draft()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "mark_draft() must set status back to DRAFT from FUTURE_DEVELOPMENT"

    def test_mark_draft_from_feature_deprecation_succeeds(self, category: Category) -> None:
        category.mark_feature_deprecation()
        category.mark_draft()
        category.refresh_from_db()
        assert (
            category.status == DataStatus.DRAFT
        ), "mark_draft() must set status back to DRAFT from FEATURE_DEPRECATION"

    def test_mark_draft_from_draft_raises(self, category: Category) -> None:
        with pytest.raises(ValidationError, match="FUTURE"):
            category.mark_draft()

    def test_mark_draft_when_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.mark_draft()


@pytest.mark.django_db
class TestApprove:
    def test_approve_from_draft_succeeds(self, category: Category) -> None:
        category.approve()
        category.refresh_from_db()
        assert category.status == DataStatus.APPROVED, "approve() must set status to APPROVED"

    def test_approve_from_future_development_succeeds(self, category: Category) -> None:
        category.mark_future_development()
        category.approve()
        category.refresh_from_db()
        assert category.status == DataStatus.APPROVED, "approve() must work from FUTURE_DEVELOPMENT status"

    def test_approve_from_feature_deprecation_succeeds(self, category: Category) -> None:
        category.mark_feature_deprecation()
        category.approve()
        category.refresh_from_db()
        assert category.status == DataStatus.APPROVED, "approve() must work from FEATURE_DEPRECATION status"

    def test_approve_already_approved_raises(self, category: Category) -> None:
        category.approve()
        with pytest.raises(ValidationError, match="already approved"):
            category.approve()

    def test_approve_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.approve()


@pytest.mark.django_db
class TestSaveLockEnforcement:
    def test_save_non_approved_to_locked_release_raises(self, locked_release: Release) -> None:
        cat = Category(name="New", release=locked_release, status=DataStatus.DRAFT)
        with pytest.raises(ValidationError, match="locked"):
            cat.save()

    def test_save_approved_to_locked_release_succeeds(self, db: None) -> None:
        r = Release.objects.create(version="v-lock-approved")
        cat = Category.objects.create(name="Cat", release=r)
        r.lock()
        # Approve via .update() to bypass save() — then verify saving APPROVED is allowed
        Category.objects.filter(pk=cat.pk).update(status=DataStatus.APPROVED)
        cat.refresh_from_db()
        cat.name = "Updated"  # should not raise — status is APPROVED
        cat.save()

    def test_save_to_unlocked_release_always_succeeds(self, release: Release) -> None:
        cat = Category(name="New", release=release, status=DataStatus.DRAFT)
        cat.save()  # must not raise

    def test_is_release_locked_uses_instance_cache(self, db: None) -> None:
        """_is_release_locked() must use the cached release object, not hit the DB."""
        r = Release.objects.create(version="v-cache-test")
        cat = Category(name="Cat", release=r)  # release is cached via direct assignment
        # Mark as locked on the Python object only — do NOT persist to DB
        r.is_locked = True
        assert cat._is_release_locked() is True, "Must read from cached release instance"  # pylint: disable=W0212

    def test_is_release_locked_falls_back_to_db(self, db: None) -> None:
        """_is_release_locked() must query DB when release is not cached."""
        r = Release.objects.create(version="v-db-fallback")
        cat = Category.objects.create(name="Cat", release=r)
        r.lock()
        # Load fresh without select_related so the FK instance is NOT in the cache
        fresh_cat = Category.objects.get(pk=cat.pk)
        release_field = fresh_cat.__class__._meta.get_field("release")  # pylint: disable=W0212
        try:
            release_field.get_cached_value(fresh_cat)
            cached = True
        except KeyError:
            cached = False
        assert not cached, "release must not be cached on a plain .get()"
        assert fresh_cat._is_release_locked() is True, "Must correctly read is_locked from DB"  # pylint: disable=W0212


@pytest.mark.django_db
class TestDeleteLockEnforcement:
    def test_delete_from_locked_release_raises(self, db: None) -> None:
        r = Release.objects.create(version="v-del-lock")
        cat = Category.objects.create(name="Cat", release=r)
        r.lock()
        cat.refresh_from_db()
        with pytest.raises(ValidationError, match="locked"):
            cat.delete()

    def test_delete_from_unlocked_release_succeeds(self, release: Release, category: Category) -> None:
        pk = category.pk
        category.delete()
        assert not Category.objects.filter(pk=pk).exists(), "Row must be deleted"


@pytest.mark.django_db
class TestApproveOnLockedRelease:
    def test_approve_works_on_locked_release(self, db: None) -> None:
        """CI workflow: lock first, then run automation to approve."""
        r = Release.objects.create(version="v-ci-flow")
        cat = Category.objects.create(name="Cat", release=r)
        r.lock()
        cat.refresh_from_db()
        cat.approve()  # must not raise — this is the intended CI workflow
        cat.refresh_from_db()
        assert cat.status == DataStatus.APPROVED, "approve() must work on locked releases"
