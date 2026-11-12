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
    def test_mark_future_deprecation_from_draft_succeeds(self, category: Category) -> None:
        category.mark_future_deprecation()
        category.refresh_from_db()
        assert (
            category.status == DataStatus.FUTURE_DEPRECATION
        ), "mark_future_deprecation() must set status to FUTURE_DEPRECATION"

    def test_mark_future_deprecation_from_approved_raises(self, category: Category) -> None:
        category.approve()
        with pytest.raises(ValidationError, match="DRAFT"):
            category.mark_future_deprecation()

    def test_mark_future_deprecation_when_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.mark_future_deprecation()


@pytest.mark.django_db
class TestMarkDraft:
    def test_mark_draft_from_future_development_succeeds(self, category: Category) -> None:
        category.mark_future_development()
        category.mark_draft()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "mark_draft() must set status back to DRAFT from FUTURE_DEVELOPMENT"

    def test_mark_draft_from_future_deprecation_succeeds(self, category: Category) -> None:
        category.mark_future_deprecation()
        category.mark_draft()
        category.refresh_from_db()
        assert category.status == DataStatus.DRAFT, "mark_draft() must set status back to DRAFT from FUTURE_DEPRECATION"

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

    def test_approve_from_future_deprecation_succeeds(self, category: Category) -> None:
        category.mark_future_deprecation()
        category.approve()
        category.refresh_from_db()
        assert category.status == DataStatus.APPROVED, "approve() must work from FUTURE_DEPRECATION status"

    def test_approve_already_approved_raises(self, category: Category) -> None:
        category.approve()
        with pytest.raises(ValidationError, match="already approved"):
            category.approve()

    def test_approve_inactive_raises(self, category: Category) -> None:
        category.deactivate()
        with pytest.raises(ValidationError, match="inactive"):
            category.approve()


@pytest.fixture(name="frozen_release")
def fixture_frozen_release(request: pytest.FixtureRequest, db: None) -> Release:  # pylint: disable=W0613
    """A release holding one DRAFT and one APPROVED Category, then locked (and deployed if param=True)."""
    r = Release.objects.create(version=f"v-frozen-{request.param}")
    Category.objects.create(name="Draft", release=r)
    Category.objects.create(name="Approved", release=r).approve()
    r.lock()
    if request.param:
        r.deploy()
    return r


@pytest.fixture(name="open_release")
def fixture_open_release(db: None) -> Release:  # pylint: disable=W0613
    return Release.objects.create(version="v-open")


FROZEN = pytest.mark.parametrize("frozen_release", [False, True], ids=["locked", "deployed"], indirect=True)


def _row(release: Release, status: DataStatus) -> Category:
    return Category.objects.get(release=release, status=status)


@pytest.mark.django_db
@FROZEN
class TestSaveLockEnforcement:
    @pytest.mark.parametrize("status", [DataStatus.DRAFT, DataStatus.APPROVED])
    def test_save_edit_on_frozen_release_raises(self, frozen_release: Release, status: DataStatus) -> None:
        row = _row(frozen_release, status)
        row.name = "Edited"
        with pytest.raises(ValidationError, match="locked"):
            row.save()
        assert _row(frozen_release, status).name != "Edited", f"{status} row must not be modified"

    @pytest.mark.parametrize("status", [DataStatus.DRAFT, DataStatus.APPROVED])
    def test_save_insert_into_frozen_release_raises(self, frozen_release: Release, status: DataStatus) -> None:
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.create(name="New", release=frozen_release, status=status)

    def test_save_flip_status_to_approved_and_edit_raises(self, frozen_release: Release) -> None:
        row = _row(frozen_release, DataStatus.DRAFT)
        row.status = DataStatus.APPROVED
        row.name = "Sneaky"
        with pytest.raises(ValidationError, match="locked"):
            row.save()

    def test_save_move_row_out_of_frozen_release_raises(self, frozen_release: Release, open_release: Release) -> None:
        row = _row(frozen_release, DataStatus.APPROVED)
        row.release = open_release
        with pytest.raises(ValidationError, match="locked"):
            row.save()
        assert Category.objects.filter(release=open_release).count() == 0, "Row must stay in the frozen release"

    def test_save_ignores_stale_cached_release(self, frozen_release: Release) -> None:
        row = Category.objects.select_related("release").get(release=frozen_release, status=DataStatus.DRAFT)
        row.release.is_locked = False  # simulate an instance loaded before the lock
        row.release.deployed = False
        with pytest.raises(ValidationError, match="locked"):
            row.save()

    @pytest.mark.parametrize("method", ["approve", "deactivate", "mark_future_development", "mark_future_deprecation"])
    def test_status_transitions_on_frozen_release_raise(self, frozen_release: Release, method: str) -> None:
        row = _row(frozen_release, DataStatus.DRAFT)
        with pytest.raises(ValidationError, match="locked"):
            getattr(row, method)()


@pytest.mark.django_db
class TestSaveUnlockedRelease:
    def test_save_to_unlocked_release_succeeds(self, release: Release) -> None:
        cat = Category(name="New", release=release, status=DataStatus.DRAFT)
        cat.save()
        assert Category.objects.filter(pk=cat.pk).exists(), "Row must be saved on an unlocked release"

    def test_save_move_row_into_locked_release_raises(self, release: Release, locked_release: Release) -> None:
        cat = Category.objects.create(name="Mover", release=release)
        cat.release = locked_release
        with pytest.raises(ValidationError, match="locked"):
            cat.save()

    def test_save_after_unlock_succeeds(self, db: None) -> None:
        r = Release.objects.create(version="v-unlock-edit")
        cat = Category.objects.create(name="Cat", release=r)
        r.lock()
        r.is_locked = False
        r.save(update_fields=["is_locked"])
        cat.name = "Fixed"
        cat.save()
        assert Category.objects.get(pk=cat.pk).name == "Fixed", "Unlocked (not deployed) release must be editable"


@pytest.mark.django_db
@FROZEN
class TestDeleteLockEnforcement:
    @pytest.mark.parametrize("status", [DataStatus.DRAFT, DataStatus.APPROVED])
    def test_delete_from_frozen_release_raises(self, frozen_release: Release, status: DataStatus) -> None:
        row = _row(frozen_release, status)
        with pytest.raises(ValidationError, match="locked"):
            row.delete()
        assert Category.objects.filter(pk=row.pk).exists(), "Row must not be deleted"


@pytest.mark.django_db
def test_delete_from_unlocked_release_succeeds(release: Release, category: Category) -> None:
    pk = category.pk
    category.delete()
    assert not Category.objects.filter(pk=pk).exists(), "Row must be deleted"


@pytest.mark.django_db
@FROZEN
class TestQuerySetLockEnforcement:
    def test_queryset_update_raises(self, frozen_release: Release) -> None:
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.filter(release=frozen_release).update(name="bulk")
        assert not Category.objects.filter(name="bulk").exists(), "No row may be updated"

    def test_queryset_update_moving_rows_into_frozen_release_raises(
        self, frozen_release: Release, release: Release
    ) -> None:
        Category.objects.create(name="Open", release=release)
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.filter(release=release).update(release=frozen_release)

    def test_queryset_delete_raises(self, frozen_release: Release) -> None:
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.filter(release=frozen_release).delete()
        assert Category.objects.filter(release=frozen_release).count() == 2, "No row may be deleted"

    def test_bulk_create_raises(self, frozen_release: Release) -> None:
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.bulk_create([Category(name="Bulk", release=frozen_release)])

    def test_bulk_update_raises(self, frozen_release: Release) -> None:
        rows = list(Category.objects.filter(release=frozen_release))
        for row in rows:
            row.name = "bulk"
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.bulk_update(rows, ["name"])

    def test_bulk_update_moving_rows_out_raises(self, frozen_release: Release, open_release: Release) -> None:
        rows = list(Category.objects.filter(release=frozen_release))
        for row in rows:
            row.release = open_release
        with pytest.raises(ValidationError, match="locked"):
            Category.objects.bulk_update(rows, ["release"])


@pytest.mark.django_db
class TestQuerySetUnlockedRelease:
    def test_queryset_update_succeeds(self, release: Release, category: Category) -> None:
        assert Category.objects.filter(release=release).update(name="bulk") == 1, "Update must apply on unlocked"

    def test_queryset_delete_succeeds(self, release: Release, category: Category) -> None:
        Category.objects.filter(release=release).delete()
        assert not Category.objects.filter(release=release).exists(), "Delete must apply on unlocked"

    def test_bulk_create_and_update_succeed(self, release: Release) -> None:
        Category.objects.bulk_create([Category(name="A", release=release), Category(name="B", release=release)])
        rows = list(Category.objects.filter(release=release))
        for row in rows:
            row.name = "C"
        assert Category.objects.bulk_update(rows, ["name"]) == 2, "bulk_update must apply on unlocked"

    def test_manager_helpers_still_chainable(self, release: Release, approved_category: Category) -> None:
        assert list(Category.objects.approved(release)) == [approved_category], "approved() must still work"
        assert Category.objects.filter(active=True).all_rows(release).count() == 1, "QuerySet helpers must chain"
