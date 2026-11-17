# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [4.0.0] - 2026-11-17

### Changed
- **Breaking:** deployed releases are now guarded on the `Release` model, not only in the services and management commands. `Release.save()` raises `ValidationError` when changing `version`, `is_locked`, `locked_at`, `deployed` or `deployed_at` of a deployed release, and `Release.delete()` raises for a deployed release. Deprecation, `description` and `based_on` stay editable.
- **Breaking:** `Release.objects` is now a `ReleaseQuerySet` manager — `update()` (and so `bulk_update()`) raises when changing those fields on a deployed release, and `delete()` raises when the QuerySet contains a deployed release.
- Lock state is read from the database, so a stale `Release` instance can't bypass these guards.

### Fixed
- Deletes that cascade from other models can no longer change a locked or deployed release. Deleting an object that locked rows point to raises `ValidationError` if the delete would remove them (`CASCADE`) or rewrite them (`SET_NULL`, `SET_DEFAULT`, `SET()`), and the whole delete is rolled back. This also covers `Release.delete()` on a locked release that still has rows — use `delete_release`.

### Added
- Database constraint `release_deployed_requires_locked` — a deployed release must be locked.

### Migration
Run `migrate`. Migration `0003` first re-locks any deployed release that was unlocked (setting `locked_at` from `deployed_at` if missing), then adds the constraint.

---

## [3.1.0] - 2026-11-17

### Added
- `delete_release` management command and `delete_release()` service — permanently delete a release together with all its versioned rows (active and inactive). Works for draft and locked releases; refused for deployed releases. Releases branched from the deleted one are kept with `based_on` cleared, and the command warns about them. Supports `--dry-run` and `--force`; prompts for confirmation by default.
- `count_release_rows()` service — number of versioned rows per model stored under a release.
- `get_child_release_versions()` service — versions of the releases branched directly from a release.

---

## [3.0.0] - 2026-11-12

### Changed
- **Breaking:** locked and deployed releases are now fully immutable. Previously, rows with `status=APPROVED` could still be edited, and new APPROVED rows could be inserted into a locked release.
- **Breaking:** `approve()` and `approve_release` now refuse locked or deployed releases. The CI flow is `approve_release -> lock_release -> deploy_release`.
- **Breaking:** `QuerySet.update()`, `QuerySet.delete()`, `bulk_create()` and `bulk_update()` on versioned models raise `ValidationError` when they touch a locked or deployed release.
- Lock state is always read from the database — a stale cached `Release` instance no longer bypasses the lock.

### Fixed
- Rows can no longer be moved out of (or into) a locked release by reassigning `release`.

### Added
- `VersionedQuerySet` — `for_release()`, `approved()` and `all_rows()` are now chainable QuerySet methods.

---

## [2.0.0] - 2026-11-10

### Changed
- **Breaking:** renamed `DataStatus.FEATURE_DEPRECATION` to `DataStatus.FUTURE_DEPRECATION`. Stored value changed from `"feature_deprecation"` to `"future_deprecation"` and label to `"Future deprecation"`.
- **Breaking:** renamed `VersionedModel.mark_feature_deprecation()` to `mark_future_deprecation()`.

### Migration
Run `makemigrations` for your versioned models, then migrate existing rows:
```python
MyModel.objects.filter(status="feature_deprecation").update(status="future_deprecation")
```

---

## [1.3.0] - 2026-11-08

### Added
- `rename_release` management command and `rename_release()` service — rename a release's version; blocked for deployed releases, validates uniqueness and length.

---

## [1.2.1]

### Changed
- Dev dependencies refreshed: bumped `pre-commit`, `pytest`, `pytest-django`; added `custom-python-logger`, `pytest-better-report`, `python-base-command`, `python-base-toolkit`; dropped `pytest-plugins` and `djangorestframework`.

### Removed
- `drf` optional extra (`django-versioned-models[drf]`) — the package does not depend on Django REST Framework.

---
