import pytest
from django.db import IntegrityError

from django_versioned_models.models import Release


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
        assert "🚀" in str(locked_release), f"Expected rocket icon in '{locked_release}'"

    def test_str_deployed_takes_priority_over_locked(self, locked_release: Release) -> None:
        locked_release.deploy()
        assert "🔒" not in str(locked_release), "Deployed icon must take priority over locked icon"

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
