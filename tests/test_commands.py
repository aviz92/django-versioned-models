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
    def test_standalone_release_is_created(self, db: None) -> None:
        call_command("create_release", release_version="v1.0.0", stdout=StringIO())
        assert Release.objects.filter(version="v1.0.0").exists(), "Standalone release must be created"

    def test_standalone_release_is_unlocked(self, db: None) -> None:
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

    def test_branched_release_source_not_found_raises(self, db: None) -> None:
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
class TestCreateReleaseCommandValidation:
    @pytest.mark.parametrize("based_on", [None, "v1.0.0-locked"], ids=["standalone", "branch"])
    def test_existing_name_raises_command_error(
        self, release: Release, locked_release: Release, based_on: str | None
    ) -> None:
        kwargs = {"based_on": based_on} if based_on else {}
        with pytest.raises(CommandError, match="already exists"):
            call_command("create_release", release_version=release.version, stdout=StringIO(), **kwargs)

    def test_empty_name_raises_command_error(self, db: None) -> None:
        with pytest.raises(CommandError, match="must not be empty"):
            call_command("create_release", release_version="  ", stdout=StringIO())

    def test_too_long_name_raises_command_error(self, db: None) -> None:
        with pytest.raises(CommandError, match="at most 50 characters"):
            call_command("create_release", release_version="x" * 60, stdout=StringIO())


@pytest.mark.django_db
class TestLockReleaseCommand:
    def test_locks_a_release(self, release: Release) -> None:
        call_command("lock_release", release_version=release.version, stdout=StringIO())
        release.refresh_from_db()
        assert release.is_locked is True, "lock_release command must lock the release"

    def test_release_not_found_raises(self, db: None) -> None:
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

    def test_release_not_found_raises(self, db: None) -> None:
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

    def test_release_not_found_raises(self, db: None) -> None:
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

    def test_release_not_found_raises(self, db: None) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("deprecate_release", release_version="ghost", stdout=StringIO())


@pytest.mark.django_db
class TestApproveReleaseCommand:
    def test_approves_all_draft_rows(self, db: None) -> None:
        r = Release.objects.create(version="v-approve")
        Category.objects.create(name="A", release=r)
        Category.objects.create(name="B", release=r)
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        assert (
            Category.objects.filter(release=r, status=DataStatus.APPROVED).count() == 2
        ), "All DRAFT rows must be approved"

    def test_skips_inactive_rows(self, db: None) -> None:
        r = Release.objects.create(version="v-approve-skip")
        active = Category.objects.create(name="Active", release=r)
        inactive = Category.objects.create(name="Inactive", release=r)
        inactive.deactivate()
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        inactive.refresh_from_db()
        assert inactive.status == DataStatus.DRAFT, "Inactive rows must not be approved"
        active.refresh_from_db()
        assert active.status == DataStatus.APPROVED, "Active DRAFT rows must be approved"

    def test_skips_future_development_rows(self, db: None) -> None:
        r = Release.objects.create(version="v-approve-future")
        cat = Category.objects.create(name="Future Cat", release=r)
        cat.mark_future_development()
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        cat.refresh_from_db()
        assert (
            cat.status == DataStatus.FUTURE_DEVELOPMENT
        ), "FUTURE_DEVELOPMENT rows must remain unchanged after approve_release"

    def test_approves_across_multiple_models(self, db: None) -> None:
        r = Release.objects.create(version="v-approve-multi")
        cat = Category.objects.create(name="Cat", release=r)
        Product.objects.create(name="Prod", release=r, category=cat)
        call_command("approve_release", release_version=r.version, stdout=StringIO())
        assert Category.objects.get(pk=cat.pk).status == DataStatus.APPROVED, "Category must be approved"
        assert Product.objects.filter(release=r, status=DataStatus.APPROVED).count() == 1, "Product must be approved"

    def test_release_not_found_raises(self, db: None) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("approve_release", release_version="ghost", stdout=StringIO())

    @pytest.mark.parametrize("deploy", [False, True], ids=["locked", "deployed"])
    def test_locked_release_raises_and_leaves_rows_untouched(
        self, release: Release, category: Category, deploy: bool
    ) -> None:
        release.lock()
        if deploy:
            release.deploy()
        with pytest.raises(CommandError, match="approve rows before locking"):
            call_command("approve_release", release_version=release.version, stdout=StringIO())
        cat = Category.objects.get(pk=category.pk)
        assert cat.status == DataStatus.DRAFT, "Rows of a locked release must stay untouched"

    def test_approve_then_lock_then_deploy_flow(self, release: Release, category: Category) -> None:
        call_command("approve_release", release_version=release.version, stdout=StringIO())
        call_command("lock_release", release_version=release.version, stdout=StringIO())
        call_command("deploy_release", release_version=release.version, stdout=StringIO())
        category.refresh_from_db()
        assert category.status == DataStatus.APPROVED, "Rows approved before lock must stay APPROVED after deploy"


@pytest.mark.django_db
class TestRenameReleaseCommand:
    def test_renames_a_release(self, release: Release) -> None:
        out = StringIO()
        call_command("rename_release", release_version=release.version, new_version="v1.0.1", stdout=out)
        release.refresh_from_db()
        assert release.version == "v1.0.1", f"Expected v1.0.1, got {release.version}"
        assert "renamed to v1.0.1" in out.getvalue(), "Success message must mention the new name"

    def test_release_not_found_raises(self, db: None) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("rename_release", release_version="ghost", new_version="v9", stdout=StringIO())

    def test_deployed_release_raises(self, locked_release: Release) -> None:
        locked_release.deploy()
        with pytest.raises(CommandError, match="cannot be renamed"):
            call_command("rename_release", release_version=locked_release.version, new_version="v9", stdout=StringIO())

    def test_existing_name_raises(self, release: Release, locked_release: Release) -> None:
        with pytest.raises(CommandError, match="already exists"):
            call_command(
                "rename_release",
                release_version=release.version,
                new_version=locked_release.version,
                stdout=StringIO(),
            )


@pytest.mark.django_db
class TestDeleteReleaseCommand:
    def test_deletes_with_force_flag(self, release: Release, product: Product) -> None:
        out = StringIO()
        call_command("delete_release", release_version=release.version, force=True, stdout=out)
        assert not Release.objects.filter(pk=release.pk).exists(), "delete_release --force must delete the release"
        assert not Product.objects.filter(pk=product.pk).exists(), "Release rows must be deleted"
        assert "testapp.Product: 1" in out.getvalue(), "Output must list deleted counts per model"

    def test_confirmation_correct_input_deletes(self, locked_release_with_data: Release) -> None:
        with patch("builtins.input", return_value=locked_release_with_data.version):
            call_command("delete_release", release_version=locked_release_with_data.version, stdout=StringIO())
        assert not Release.objects.filter(pk=locked_release_with_data.pk).exists(), "Confirmed delete must succeed"

    def test_confirmation_wrong_input_raises(self, release: Release) -> None:
        with patch("builtins.input", return_value="wrong-version"):
            with pytest.raises(CommandError, match="Confirmation failed"):
                call_command("delete_release", release_version=release.version, stdout=StringIO())
        assert Release.objects.filter(pk=release.pk).exists(), "Failed confirmation must keep the release"

    def test_dry_run_deletes_nothing(self, release: Release, product: Product) -> None:
        out = StringIO()
        call_command("delete_release", release_version=release.version, dry_run=True, stdout=out)
        assert Release.objects.filter(pk=release.pk).exists(), "Dry run must keep the release"
        assert "Dry run" in out.getvalue(), "Dry run must say nothing was deleted"
        assert "testapp.Category: 1" in out.getvalue(), "Dry run must list what would be deleted"

    def test_release_not_found_raises(self, db: None) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            call_command("delete_release", release_version="ghost", force=True, stdout=StringIO())

    def test_deployed_release_raises(self, locked_release: Release) -> None:
        locked_release.deploy()
        with pytest.raises(CommandError, match="cannot be deleted"):
            call_command("delete_release", release_version=locked_release.version, force=True, stdout=StringIO())
        assert Release.objects.filter(pk=locked_release.pk).exists(), "Deployed release must survive"

    def test_child_release_prints_warning_and_keeps_child(self, locked_release_with_data: Release) -> None:
        call_command(
            "create_release",
            release_version="v3.0.0",
            based_on=locked_release_with_data.version,
            stdout=StringIO(),
        )
        out = StringIO()
        call_command("delete_release", release_version=locked_release_with_data.version, force=True, stdout=out)
        assert "is the base of: v3.0.0" in out.getvalue(), "Must warn about branched releases"
        child = Release.objects.get(version="v3.0.0")
        assert child.based_on is None, "Child release must survive with based_on cleared"
