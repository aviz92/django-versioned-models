# django-versioned-models

![PyPI version](https://img.shields.io/pypi/v/django-versioned-models)
![Python](https://img.shields.io/badge/python->=3.12-blue)
![Development Status](https://img.shields.io/badge/status-stable-green)
![Maintenance](https://img.shields.io/maintenance/yes/2026)
![PyPI](https://img.shields.io/pypi/dm/django-versioned-models)
![License](https://img.shields.io/pypi/l/django-versioned-models)

---

Drop-in versioning for Django models. Every model that inherits from `VersionedModel` gets full release management, a data status workflow, and CI integration — automatically.

---

## 🚀 Features

- **Release management** — every row in every table is tagged to a release. Branch, lock, patch, and deprecate with simple commands.
- **Data status workflow** — `DRAFT → FUTURE_DEVELOPMENT / FUTURE_DEPRECATION → APPROVED`. CI only sees approved rows. Live architect edits never break tests.
- **Lock enforcement** — locked and deployed releases are fully immutable at the model and QuerySet level. No edits, inserts, approvals, or deletes — from Admin, API, shell, or bulk operations. Deployed releases themselves can't be unlocked, renamed, or deleted, enforced in the model and the database.
- **Soft-delete** — rows can be deactivated without deletion. Deactivating an approved row resets it to `DRAFT` so it must be re-approved before CI sees it again.
- **Auto-discovery** — inherit `VersionedModel` and your model is versioned. No registration needed.
- **Topological FK sort** — models are duplicated in the correct dependency order automatically when branching a release. Many-to-many links are copied too, remapped to the new release's rows. Rows are inserted in batches of 1,000, so branching runs a handful of queries per model instead of two per row.
- **Soft deprecation** — old releases are hidden by default but data is always preserved and reversible.
- **CI-ready commands** — `create_release`, `approve_release`, `lock_release`, and more, ready to plug into any pipeline.

---

## 📦 Installation

```bash
pip install django-versioned-models
```

---

## ⚡ Quick Start

### 1. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    ...
    "django_versioned_models",
]
```

### 2. Run migrations

```bash
python manage.py migrate
```

### 3. Define your versioned models

```python
from django.db import models
from django_versioned_models.mixins import VersionedModel

class Product(VersionedModel):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta(VersionedModel.Meta):
        unique_together = [("release", "name")]  # unique per release, not globally
```

> **Important:** always inherit `Meta` from `VersionedModel.Meta` to preserve the composite index on `(release, status, active)`.

### 4. Run migrations for your models

```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Create the first release

```bash
python manage.py create_release --release-version v1.0.0
```

### 6. Add data, then lock

```bash
# Add data via Admin, API, or shell — all rows start as DRAFT

python manage.py lock_release --release-version v1.0.0
```

---

## 🔄 Ongoing Workflow

```
create_release → architects edit (DRAFT) → approve_release → lock_release → deploy_release → ship
```

```bash
# Branch from the previous locked release
python manage.py create_release --release-version v1.1.0 --based-on v1.0.0

# Architects add and edit rows (status=DRAFT by default)

# Need a correction? Unlock is allowed before deployment
python manage.py unlock_release --release-version v1.1.0          # interactive
python manage.py unlock_release --release-version v1.1.0 --force  # CI / automation

# CI approves all stable DRAFT rows (FUTURE_DEVELOPMENT / FUTURE_DEPRECATION rows are left untouched)
# Must run before lock_release — locked releases reject approval
python manage.py approve_release --release-version v1.1.0

# Run tests against approved data only
pytest

# Lock — no more edits (including approvals) after this point, then deploy
python manage.py lock_release --release-version v1.1.0
python manage.py deploy_release --release-version v1.1.0  # requires locked — permanently blocks unlock

# Bug found after deployment? Create a patch — never unlock a deployed release
python manage.py create_release --release-version v1.1.1 --based-on v1.1.0
```

---

## 🔍 How It Works

Every model that inherits from `VersionedModel` automatically gets:

| Field | Type | Description |
|-------|------|-------------|
| `release` | FK → `Release` | Which release this row belongs to |
| `status` | CharField | Data readiness: `draft` / `future_development` / `future_deprecation` / `approved` |
| `active` | BooleanField | Soft-delete flag. Inactive rows are invisible to `for_release()` and `approved()` |

**`Release` state fields:**

| Field | Type | Description |
|-------|------|-------------|
| `is_locked` | BooleanField | Immutable — no edits or deletes allowed |
| `deployed` | BooleanField | Deployed to production — unlock is permanently blocked |
| `is_deprecated` | BooleanField | Hidden by default, data preserved |

### Status Flow

```
DRAFT <-> FUTURE_DEVELOPMENT -> APPROVED   (APPROVED is one-way — CI only)
DRAFT <-> FUTURE_DEPRECATION -> APPROVED   (APPROVED is one-way — CI only)
```

| Status | Set by | Meaning |
|--------|--------|---------|
| `DRAFT` | Architects | Being worked on |
| `FUTURE_DEVELOPMENT` | Architects | Planned addition — not ready yet (`mark_future_development()`) |
| `FUTURE_DEPRECATION` | Architects | Planned removal — not ready yet (`mark_future_deprecation()`) |
| `APPROVED` | CI only | Stable — what tests run against |

### Active / Inactive (Soft-Delete)

```python
row.deactivate()   # sets active=False, resets APPROVED → DRAFT
row.reactivate()   # sets active=True, status stays DRAFT — must re-approve
```

Deactivating an approved row resets its status to `DRAFT`, so it must go through the approval flow again before CI can see it.

### Lock Enforcement

Locked and deployed releases are immutable. Every write raises `ValidationError` — whatever the row's status, from Admin, API, or shell:

```python
row.save()     # edit or insert — raises if the row's current or target release is locked
row.delete()   # raises if release is locked
row.approve()  # raises — approve before locking

Product.objects.filter(release=locked).update(...)  # raises
Product.objects.filter(release=locked).delete()     # raises
Product.objects.bulk_create([...])                  # raises if any row targets a locked release
Product.objects.bulk_update([...], fields)          # raises if any row is in / moves to a locked release
```

Lock state is always read from the database, so a stale `Release` instance can't bypass the check. Need a correction before deployment? `unlock_release`, fix, re-approve, lock again. After deployment, create a patch release.

The same holds for deletes that cascade from other models. Deleting an object that locked rows point to raises if the delete would remove them (`CASCADE`) or rewrite them (`SET_NULL`, `SET_DEFAULT`, `SET()`), and the whole delete is rolled back:

```python
supplier.delete()                    # raises if a locked Part has supplier=FK(..., on_delete=CASCADE)
Supplier.objects.filter(...).delete()  # same
locked_release.delete()              # raises if the release still has rows — use delete_release
```

Many-to-many links of locked rows are frozen as well — `add()`, `remove()`, `clear()` and `set()` raise from either side of the relation, and so does deleting an object that would cascade into those links:

```python
locked_part.tags.add(tag)   # raises
tag.parts.clear()           # raises if any linked part is in a locked release
```

Like an integrity error, this is raised inside the delete's transaction — inside an outer `atomic()` block, exit it (or wrap the delete in a nested `atomic()`) before running more queries.

The one deliberate exception is `delete_release`: it removes a non-deployed release (locked or not) together with all its rows.

#### Release isolation

Releases are fully isolated: a versioned row may only point to rows of its own release. Otherwise an unlocked row in one release could change what a locked row in another release refers to. Every write that would create such a reference raises `ValidationError` — `save()`, `create()`, `QuerySet.update()`, `bulk_create()`, `bulk_update()` and many-to-many `add()` / `set()`:

```python
part.parent = part_from_another_release
part.save()                                   # raises
part.tags.add(tag_from_another_release)       # raises
row.release = other_release; row.save()       # raises — rows can't move between releases
```

References to non-versioned models (shared by all releases, such as users) are not checked. A database written by an earlier version may already hold references that cross releases — find them with `python manage.py check_release_isolation`. Such a row can still be saved with `update_fields` that leave the bad reference out, and its release can't be branched until the reference is fixed.

#### Deployed releases

A deployed release is guarded on the `Release` model itself, not only by the management commands:

```python
release.is_locked = False; release.save()            # raises — also version, locked_at, deployed, deployed_at
release.delete()                                     # raises
Release.objects.filter(...).update(is_locked=False)  # raises if any matched release is deployed
Release.objects.filter(...).delete()                 # raises if any matched release is deployed
release.deprecate()                                  # allowed — as are description and based_on edits
```

A database constraint (`release_deployed_requires_locked`) also guarantees a deployed release is always locked.

---

## 🖥 Admin and Forms

The rules above are also checked before anything is written, so forms show them as errors instead of failing on save:

- **Any `ModelForm`** — `VersionedModel.clean()` reports a locked or deployed release, a row moved to another release, and FK / one-to-one references into another release. Errors are attached to the offending field, or to the whole form when that field isn't on it. If you override `clean()`, call `super().clean()`.
- **The Django admin** — use `VersionedModelAdmin`:

```python
from django.contrib import admin
from django_versioned_models.admin import VersionedModelAdmin

@admin.register(Product)
class ProductAdmin(VersionedModelAdmin):
    list_display = ["name", "release", "status"]
```

It makes rows of a locked or deployed release read-only (no save, no delete), lists only rows of the edited row's release in FK and many-to-many choices, checks many-to-many selections against the row's release, and refuses — on the confirmation page — a delete that would cascade into rows of a locked release, for the delete view and the "delete selected" action alike. Use it for non-versioned models that versioned rows point to as well, so deleting them from the admin is checked too. For your own forms with many-to-many fields, subclass `VersionedModelForm`.

---

## 💾 Fixtures, Backup and Restore

`loaddata` saves rows "raw", past `save()` — so the library checks raw saves separately. Loading a fixture is refused when it would write rows of a locked or deployed release, move a row to another release, point a row into another release, or change a deployed release. Loading into unlocked releases works as usual.

To restore a full dump that contains locked or deployed releases, use `restore_releases` instead of `loaddata`. It loads with the lock check lifted, then verifies that no reference crosses releases; if one does, the whole load is rolled back:

```bash
python manage.py dumpdata django_versioned_models myapp > dump.json
python manage.py restore_releases dump.json
```

Data migrations (`RunPython`) work on historical models without this library's code, so they are not checked — run `check_release_isolation` after one that touches versioned data.

---

## 📋 Management Commands

| Command | Description |
|---------|-------------|
| `create_release --release-version v1.0.0` | Create a standalone release (unlocked) |
| `create_release --release-version v1.1.0 --based-on v1.0.0` | Branch from a locked release — copies all rows and their many-to-many links |
| `lock_release --release-version v1.1.0` | Lock a release (immutable) |
| `approve_release --release-version v1.1.0` | Approve all active DRAFT rows (CI only — FUTURE_DEVELOPMENT, FUTURE_DEPRECATION, and inactive untouched) |
| `deploy_release --release-version v1.1.0` | Mark as deployed — permanently blocks unlock |
| `unlock_release --release-version v1.1.0` | Unlock with interactive confirmation (pre-deployment only) |
| `unlock_release --release-version v1.1.0 --force` | Unlock without prompt — safe for CI/automation (pre-deployment only) |
| `rename_release --release-version v1.1.0 --new-version v1.1.0-rc` | Rename a release (data untouched; blocked for deployed releases) |
| `delete_release --release-version v1.1.0` | Permanently delete a release and all its rows, with interactive confirmation (blocked for deployed releases; branches of it are kept but lose their `based_on`, with a warning) |
| `delete_release --release-version v1.1.0 --dry-run` | Show what would be deleted, without deleting |
| `delete_release --release-version v1.1.0 --force` | Delete without prompt — for CI/automation |
| `restore_releases dump.json` | Restore a full dump that contains locked or deployed releases (plain `loaddata` refuses it); rolled back if any reference crosses releases |
| `check_release_isolation` | Read-only scan for references that cross releases; exits with an error if any are found (CI-friendly) |
| `deprecate_release --release-version v1.0.0` | Soft-deprecate (data preserved, hidden by default) |
| `deprecate_release --release-version v1.0.0 --undo` | Restore a deprecated release |

---

### Branching and `save()`

`create_release` copies rows with `bulk_create`, which does not call the model's `save()` or send `pre_save` / `post_save`. If a versioned model relies on them, opt it out — it is then copied row by row with `save()`:

```python
class Product(VersionedModel):
    copy_with_bulk_create = False
```

The same row-by-row path is used automatically for databases that can't return primary keys from a bulk insert (MySQL).

Proxy models of a versioned model are fine — they share its table and are not copied separately. Multi-table inheritance from a versioned model is not supported.

---

## 🗄 Querying

```python
from django_versioned_models.models import Release

release = Release.objects.get(version="v1.1.0")

# Active rows only, all statuses — use in architect-facing GUI views
Product.objects.for_release(release)

# Approved + active rows only — use in CI and production logic
Product.objects.approved(release)

# All rows including inactive — use for copy/audit only, not business logic
Product.objects.all_rows(release)

# Filter by status directly
Product.objects.for_release(release).filter(status=DataStatus.FUTURE_DEPRECATION)
```

---

## 📥 Imports Reference

```python
from django_versioned_models.mixins import VersionedModel, DataStatus
from django_versioned_models.models import Release
from django_versioned_models.admin import VersionedModelAdmin, VersionedModelForm
from django_versioned_models.services import (
    create_release,
    approve_release,
    lock_release,
    unlock_release,
    deploy_release,
    deprecate_release,
    rename_release,
    delete_release,
    find_cross_release_references,
    get_versioned_models,
    get_versioned_models_ordered,
)
```

---

## 🧪 Running Tests

```bash
uv run pytest
```

---

## 🤝 Contributing

Contributions are welcome! Please fork the repo, create a branch, and submit a pull request.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
