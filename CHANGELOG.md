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
- During `create_release`, versioned rows are inserted with `bulk_create`, which skips `save()` and the `pre_save` / `post_save` signals. Set `copy_with_bulk_create = False` on a model to copy it row by row with `save()`. Multi-table inheritance and databases that can't return bulk-inserted keys (MySQL) fall back to row by row automatically.

### Performance
- `create_release` copies rows in batches of 1,000 with `bulk_create` instead of one `save()` per row, and no longer runs the lock check for every row it writes into the release it is building (that release is created unlocked inside the same transaction and isn't visible to other connections). Branching runs a handful of queries per model instead of two per row — about 25 queries instead of 22,000 for 11,000 rows. The 3.0.0 per-row lock check had doubled the query count.
- Rows are read in batches too, and the old-to-new mapping keeps only primary keys, so memory no longer grows with full row objects.

### Fixed
- `lock_release` usage example in its module docstring used the old `--version` flag; it is `--release-version`.
- Proxy models of versioned models are no longer treated as separate versioned models. They share their model's table, so `create_release` copied those rows twice, and `count_release_rows`, `delete_release --dry-run` and `approve_release` went over them twice.
- `create_release` no longer leaves self-references pointing into the source release. A row that points to another row of the same model (a parent/child tree) is remapped in a second pass, so the copy order doesn't matter — cycles and rows pointing to themselves included. A non-nullable self-reference can't be set that way and now raises `ValueError`.
- `create_release` remaps one-to-one fields between versioned models (previously the branch failed on a uniqueness violation), and orders one-to-one targets before the models that point to them.
- `create_release` raises `ValueError` and rolls back when a row points to a versioned row outside the source release, instead of silently keeping a reference into another release.
- `create_release` no longer fails when a versioned model has a foreign key to a non-versioned model — the copy keeps pointing to the same shared object.
- `create_release` no longer fails on versioned models with a many-to-many field. Links are copied after all rows, each versioned end remapped to its copy in the new release; non-versioned ends and extra fields of a custom through model are kept, and a versioned through model is copied once like any versioned model. A link to a versioned row outside the source release raises `ValueError` and the branch is rolled back.
- Many-to-many links of locked or deployed rows can no longer be changed: `add()`, `remove()`, `clear()` and `set()` raise `ValidationError` from either side, as does a delete that would cascade into those links.
- Deletes that cascade from other models can no longer change a locked or deployed release. Deleting an object that locked rows point to raises `ValidationError` if the delete would remove them (`CASCADE`) or rewrite them (`SET_NULL`, `SET_DEFAULT`, `SET()`), and the whole delete is rolled back. This also covers `Release.delete()` on a locked release that still has rows — use `delete_release`.

### Added
- `approve_release()`, `unlock_release()`, `deploy_release()` and `deprecate_release()` services. Every management command now delegates to the services layer, so the same rules apply from code, an API view or the shell; the commands only parse arguments, confirm and print. Command behavior and messages are unchanged. Release state changes now lock the release row (`select_for_update`) while they run.
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
