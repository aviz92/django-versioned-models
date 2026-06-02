from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from tests.testapp.models import Category, Product


@pytest.mark.django_db
class TestCreateReleaseCommand:
    def test_standalone_release_is_created(self, db) -> None:
        call_command("create_release", release_version="v1.0.0", stdout=StringIO())
        assert Release.objects.filter(version="v1.0.0").exists(), "Standalone release must be created"

    def test_standalone_release_is_unlocked(self, db) -> None:
        call_command("create_release", release_version="v1.0.0", stdout=StringIO())
        r = Release.objects.get(version="v1.0.0")
        assert r.is_locked is False, "Standalone release must be unlocked"

    def test_branched_release_copies_data(self, locked_release_with_data: Release) -> None:
        call_command(
            "create_release",
            release_version="v3.0.0",
            based_on=locked_release_with_data.version,
            stdout=StringIO(),
        )
        new = Release.objects.get(version="v3.0.0")
        assert Category.objects.all_rows(new).count() > 0, "Branched release must copy rows"

    def test_branched_release_source_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command(
                "create_release",
                release_version="v2.0.0",
                based_on="nonexistent",
                stdout=StringIO(),
            )

    def test_branched_release_source_not_locked_raises(self, release: Release) -> None:
        with pytest.raises(CommandError, match="not locked"):
            call_command(
                "create_release",
                release_version="v2.0.0",
                based_on=release.version,
                stdout=StringIO(),
            )


@pytest.mark.django_db
class TestLockReleaseCommand:
    def test_locks_a_release(self, release: Release) -> None:
        call_command("lock_release", release_version=release.version, stdout=StringIO())
        release.refresh_from_db()
        assert release.is_locked is True, "lock_release command must lock the release"

    def test_release_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("lock_release", release_version="ghost", stdout=StringIO())

    def test_already_locked_raises(self, locked_release: Release) -> None:
        with pytest.raises(CommandError, match="already locked"):
            call_command("lock_release", release_version=locked_release.version, stdout=StringIO())


@pytest.mark.django_db
class TestUnlockReleaseCommand:
    def test_unlocks_with_force_flag(self, locked_release: Release) -> None:
        call_command("unlock_release", release_version=locked_release.version, force=True, stdout=StringIO())
        locked_release.refresh_from_db()
        assert locked_release.is_locked is False, "unlock_release --force must unlock the release"

    def test_unlock_clears_locked_at(self, locked_release: Release) -> None:
        call_command("unlock_release", release_version=locked_release.version, force=True, stdout=StringIO())
        locked_release.refresh_from_db()
        assert locked_release.locked_at is None, "locked_at must be cleared after unlock"

    def test_release_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("unlock_release", release_version="ghost", force=True, stdout=StringIO())

    def test_not_locked_raises(self, release: Release) -> None:
        with pytest.raises(CommandError, match="not locked"):
            call_command("unlock_release", release_version=release.version, force=True, stdout=StringIO())

    def test_confirmation_correct_input_succeeds(self, locked_release: Release) -> None:
        with patch("builtins.input", return_value=locked_release.version):
            call_command("unlock_release", release_version=locked_release.version, stdout=StringIO())
        locked_release.refresh_from_db()
        assert locked_release.is_locked is False, "Correct confirmation must unlock the release"

    def test_confirmation_wrong_input_raises(self, locked_release: Release) -> None:
        with patch("builtins.input", return_value="wrong-version"):
            with pytest.raises(CommandError, match="Confirmation failed"):
                call_command("unlock_release", release_version=locked_release.version, stdout=StringIO())

    def test_deployed_release_cannot_be_unlocked(self, locked_release: Release) -> None:
        locked_release.deploy()
        with pytest.raises(CommandError, match="deployed to production"):
            call_command("unlock_release", release_version=locked_release.version, force=True, stdout=StringIO())


@pytest.mark.django_db
class TestDeployReleaseCommand:
    def test_marks_release_as_deployed(self, locked_release: Release) -> None:
        call_command("deploy_release", release_version=locked_release.version, stdout=StringIO())
        locked_release.refresh_from_db()
        assert locked_release.deployed is True, "deploy_release must set deployed=True"

    def test_sets_deployed_at_timestamp(self, locked_release: Release) -> None:
        call_command("deploy_release", release_version=locked_release.version, stdout=StringIO())
        locked_release.refresh_from_db()
        assert locked_release.deployed_at is not None, "deployed_at must be set"

    def test_release_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("deploy_release", release_version="ghost", stdout=StringIO())

    def test_already_deployed_raises(self, locked_release: Release) -> None:
        locked_release.deploy()
        with pytest.raises(CommandError, match="already deployed"):
            call_command("deploy_release", release_version=locked_release.version, stdout=StringIO())

    def test_unlocked_release_raises(self, release: Release) -> None:
        with pytest.raises(CommandError, match="must be locked"):
            call_command("deploy_release", release_version=release.version, stdout=StringIO())


@pytest.mark.django_db
class TestDeprecateReleaseCommand:
    def test_deprecates_a_release(self, release: Release) -> None:
        call_command("deprecate_release", release_version=release.version, stdout=StringIO())
        release.refresh_from_db()
        assert release.is_deprecated is True, "deprecate_release must mark release as deprecated"

    def test_already_deprecated_raises(self, release: Release) -> None:
        release.deprecate()
        with pytest.raises(CommandError, match="already deprecated"):
            call_command("deprecate_release", release_version=release.version, stdout=StringIO())

    def test_undo_undeprecates_a_release(self, release: Release) -> None:
        release.deprecate()
        call_command("deprecate_release", release_version=release.version, undo=True, stdout=StringIO())
        release.refresh_from_db()
        assert release.is_deprecated is False, "undo must clear is_deprecated"

    def test_undo_not_deprecated_raises(self, release: Release) -> None:
        with pytest.raises(CommandError, match="not deprecated"):
            call_command("deprecate_release", release_version=release.version, undo=True, stdout=StringIO())

    def test_release_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("deprecate_release", release_version="ghost", stdout=StringIO())


@pytest.mark.django_db
class TestApproveReleaseCommand:
    def test_approves_all_draft_rows(self, db) -> None:
        r = Release.objects.create(version="v-approve")
        Category.objects.create(name="A", release=r)
        Category.objects.create(name="B", release=r)
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        assert (
            Category.objects.filter(release=r, status=DataStatus.APPROVED).count() == 2
        ), "All DRAFT rows must be approved"

    def test_skips_inactive_rows(self, db) -> None:
        r = Release.objects.create(version="v-approve-skip")
        active = Category.objects.create(name="Active", release=r)
        inactive = Category.objects.create(name="Inactive", release=r)
        inactive.deactivate()
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        inactive.refresh_from_db()
        assert inactive.status == DataStatus.DRAFT, "Inactive rows must not be approved"
        active.refresh_from_db()
        assert active.status == DataStatus.APPROVED, "Active DRAFT rows must be approved"

    def test_skips_future_rows(self, db) -> None:
        r = Release.objects.create(version="v-approve-future")
        cat = Category.objects.create(name="Future Cat", release=r)
        cat.mark_future()
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        cat.refresh_from_db()
        assert cat.status == DataStatus.FUTURE, "FUTURE rows must remain FUTURE after approve_release"

    def test_approves_across_multiple_models(self, db) -> None:
        r = Release.objects.create(version="v-approve-multi")
        cat = Category.objects.create(name="Cat", release=r)
        Product.objects.create(name="Prod", release=r, category=cat)
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        assert Category.objects.get(pk=cat.pk).status == DataStatus.APPROVED, "Category must be approved"
        assert Product.objects.filter(release=r, status=DataStatus.APPROVED).count() == 1, "Product must be approved"

    def test_release_not_found_raises(self, db) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("approve_release", release_version="ghost", stdout=StringIO())
