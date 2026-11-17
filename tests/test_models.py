import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from django_versioned_models.models import Release
from tests.testapp.models import Category


@pytest.mark.django_db
class TestReleaseStr:
    def test_str_unlocked_shows_pencil_icon(self, release: Release) -> None:
        assert "✏️" in str(release), f"Expected pencil icon in '{release}'"

    def test_str_locked_shows_lock_icon(self, locked_release: Release) -> None:
        assert "🔒" in str(locked_release), f"Expected lock icon in '{locked_release}'"

    def test_str_deprecated_shows_archive_icon(self, release: Release) -> None:
        release.deprecate()
        assert "🗄" in str(release), f"Expected archive icon in '{release}'"

    def test_str_contains_version(self, release: Release) -> None:
        assert release.version in str(release), "Version must appear in __str__"


@pytest.mark.django_db
class TestReleaseLock:
    def test_lock_sets_is_locked_true(self, release: Release) -> None:
        release.lock()
        release.refresh_from_db()
        assert release.is_locked is True, "is_locked should be True after lock()"

    def test_lock_sets_locked_at_timestamp(self, release: Release) -> None:
        assert release.locked_at is None, "locked_at should be None before lock()"
        release.lock()
        release.refresh_from_db()
        assert release.locked_at is not None, "locked_at must be set after lock()"

    def test_lock_only_updates_relevant_fields(self, release: Release) -> None:
        original_version = release.version
        release.lock()
        release.refresh_from_db()
        assert release.version == original_version, "lock() must not change other fields"


@pytest.mark.django_db
class TestReleaseDeprecate:
    def test_deprecate_sets_is_deprecated_true(self, release: Release) -> None:
        release.deprecate()
        release.refresh_from_db()
        assert release.is_deprecated is True, "is_deprecated should be True after deprecate()"

    def test_deprecate_sets_deprecated_at_timestamp(self, release: Release) -> None:
        assert release.deprecated_at is None, "deprecated_at should be None before deprecate()"
        release.deprecate()
        release.refresh_from_db()
        assert release.deprecated_at is not None, "deprecated_at must be set after deprecate()"

    def test_undeprecate_clears_is_deprecated(self, release: Release) -> None:
        release.deprecate()
        release.undeprecate()
        release.refresh_from_db()
        assert release.is_deprecated is False, "is_deprecated should be False after undeprecate()"

    def test_undeprecate_clears_deprecated_at(self, release: Release) -> None:
        release.deprecate()
        release.undeprecate()
        release.refresh_from_db()
        assert release.deprecated_at is None, "deprecated_at must be None after undeprecate()"


@pytest.mark.django_db
class TestReleaseDeploy:
    def test_deploy_sets_deployed_true(self, locked_release: Release) -> None:
        locked_release.deploy()
        locked_release.refresh_from_db()
        assert locked_release.deployed is True, "deploy() must set deployed=True"

    def test_deploy_sets_deployed_at_timestamp(self, locked_release: Release) -> None:
        assert locked_release.deployed_at is None, "deployed_at must be None before deploy()"
        locked_release.deploy()
        locked_release.refresh_from_db()
        assert locked_release.deployed_at is not None, "deployed_at must be set after deploy()"

    def test_deploy_requires_locked_release(self, release: Release) -> None:
        with pytest.raises(ValueError, match="must be locked"):
            release.deploy()

    def test_str_deployed_shows_rocket_icon(self, locked_release: Release) -> None:
        locked_release.deploy()
        assert (
            str(locked_release) == f"🔒🚀 {locked_release.version}"
        ), f"Expected lock+rocket icon in '{locked_release}'"

    def test_str_deployed_takes_priority_over_locked(self, locked_release: Release) -> None:
        locked_release.deploy()
        assert not str(locked_release).startswith("🔒 "), "Deployed icon must take priority over plain locked icon"

    def test_str_deprecated_takes_priority_over_deployed(self, locked_release: Release) -> None:
        locked_release.deploy()
        locked_release.deprecate()
        assert "🗄" in str(locked_release), "Deprecated icon must take priority over deployed icon"


@pytest.mark.django_db
class TestReleaseConstraints:
    def test_version_must_be_unique(self, release: Release) -> None:
        with pytest.raises(IntegrityError):
            Release.objects.create(version=release.version)

    def test_based_on_self_reference(self, release: Release, locked_release: Release) -> None:
        child = Release.objects.create(version="v2.0.0", based_on=locked_release)
        assert child.based_on == locked_release, "based_on FK must be stored correctly"

    def test_created_by_defaults_to_null(self, db: None) -> None:
        r = Release.objects.create(version="v99.0.0")
        assert r.created_by is None, "created_by must default to None"


@pytest.mark.django_db
class TestDeployedReleaseSave:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("is_locked", False),
            ("locked_at", None),
            ("deployed", False),
            ("deployed_at", None),
            ("version", "v-renamed"),
        ],
    )
    def test_save_frozen_field_raises_and_keeps_db_row(
        self, deployed_release: Release, field: str, value: object
    ) -> None:
        original = getattr(deployed_release, field)
        setattr(deployed_release, field, value)
        with pytest.raises(ValidationError, match="is deployed"):
            deployed_release.save()
        stored = Release.objects.get(pk=deployed_release.pk)
        assert getattr(stored, field) == original, f"{field} must stay unchanged in the DB"

    def test_save_with_update_fields_skips_unwritten_frozen_fields(self, deployed_release: Release) -> None:
        deployed_release.is_locked = False  # in-memory only — not written
        deployed_release.description = "Edited"
        deployed_release.save(update_fields=["description"])
        stored = Release.objects.get(pk=deployed_release.pk)
        assert stored.description == "Edited", "Non-frozen field must be saved"
        assert stored.is_locked is True, "Unwritten frozen field must stay locked"

    def test_save_with_update_fields_including_frozen_field_raises(self, deployed_release: Release) -> None:
        deployed_release.is_locked = False
        with pytest.raises(ValidationError, match="cannot change is_locked"):
            deployed_release.save(update_fields=["is_locked"])

    def test_stale_instance_cannot_unlock_deployed_release(self, locked_release: Release) -> None:
        stale = Release.objects.get(pk=locked_release.pk)
        locked_release.deploy()
        stale.is_locked = False
        with pytest.raises(ValidationError, match="is deployed"):
            stale.save()

    def test_deprecate_deployed_release_succeeds(self, deployed_release: Release) -> None:
        deployed_release.deprecate()
        assert Release.objects.get(pk=deployed_release.pk).is_deprecated is True, "Deployed release can be deprecated"

    def test_unlock_non_deployed_release_succeeds(self, locked_release: Release) -> None:
        locked_release.is_locked = False
        locked_release.save()
        assert Release.objects.get(pk=locked_release.pk).is_locked is False, "Non-deployed release can be unlocked"


@pytest.mark.django_db
class TestDeployedReleaseDelete:
    def test_delete_deployed_release_raises_and_keeps_rows(self, db: None) -> None:
        r = Release.objects.create(version="v-deployed")
        Category.objects.create(name="Keep", release=r)
        r.lock()
        r.deploy()
        with pytest.raises(ValidationError, match="deployed and cannot be deleted"):
            r.delete()
        assert Release.objects.filter(pk=r.pk).exists(), "Deployed release must survive"
        assert Category.objects.all_rows(r).count() == 1, "Deployed release rows must survive"

    def test_stale_instance_cannot_delete_deployed_release(self, locked_release: Release) -> None:
        stale = Release.objects.get(pk=locked_release.pk)
        locked_release.deploy()
        with pytest.raises(ValidationError, match="deployed and cannot be deleted"):
            stale.delete()

    def test_delete_locked_release_succeeds(self, locked_release: Release) -> None:
        locked_release.delete()
        assert not Release.objects.filter(pk=locked_release.pk).exists(), "Non-deployed release can be deleted"


@pytest.mark.django_db
class TestReleaseQuerySetGuards:
    def test_queryset_delete_with_deployed_release_raises(self, release: Release, deployed_release: Release) -> None:
        with pytest.raises(ValidationError, match=deployed_release.version):
            Release.objects.all().delete()
        assert Release.objects.count() == 2, "Nothing must be deleted"

    def test_queryset_delete_without_deployed_release_succeeds(
        self, release: Release, deployed_release: Release
    ) -> None:
        Release.objects.filter(deployed=False).delete()
        assert list(Release.objects.all()) == [deployed_release], "Only the deployed release must remain"

    def test_queryset_update_frozen_field_on_deployed_raises(self, deployed_release: Release) -> None:
        with pytest.raises(ValidationError, match="cannot change is_locked"):
            Release.objects.filter(pk=deployed_release.pk).update(is_locked=False)
        assert Release.objects.get(pk=deployed_release.pk).is_locked is True, "Release must stay locked"

    def test_queryset_update_non_frozen_field_on_deployed_succeeds(self, deployed_release: Release) -> None:
        Release.objects.filter(pk=deployed_release.pk).update(description="Edited")
        assert Release.objects.get(pk=deployed_release.pk).description == "Edited", "Description must update"

    def test_queryset_update_frozen_field_on_non_deployed_succeeds(self, locked_release: Release) -> None:
        Release.objects.filter(pk=locked_release.pk).update(is_locked=False)
        assert Release.objects.get(pk=locked_release.pk).is_locked is False, "Non-deployed release can be unlocked"

    def test_bulk_update_frozen_field_on_deployed_raises(self, deployed_release: Release) -> None:
        deployed_release.version = "v-bulk"
        with pytest.raises(ValidationError, match="cannot change version"):
            Release.objects.bulk_update([deployed_release], ["version"])


@pytest.mark.django_db
class TestDeployedRequiresLockedConstraint:
    def test_deployed_unlocked_row_violates_constraint(self, db: None) -> None:
        with pytest.raises(IntegrityError), transaction.atomic():
            Release.objects.create(version="v-bad", deployed=True, is_locked=False)


@pytest.mark.django_db(transaction=True)
class TestRelockMigration:
    def test_migration_relocks_deployed_unlocked_release(self) -> None:
        app = "django_versioned_models"
        executor = MigrationExecutor(connection)
        executor.migrate([(app, "0002_release_deployed")])
        old_release = executor.loader.project_state([(app, "0002_release_deployed")]).apps.get_model(app, "Release")
        old_release.objects.create(version="v-legacy", deployed=True, is_locked=False)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([(app, "0003_release_deployed_requires_locked")])

        migrated = Release.objects.get(version="v-legacy")
        assert migrated.is_locked is True, "Migration must re-lock deployed releases"
        assert migrated.locked_at is not None, "Migration must set locked_at"
