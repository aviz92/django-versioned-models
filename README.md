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
- **Data status workflow** — `DRAFT → FUTURE → APPROVED`. CI only sees approved rows. Live architect edits never break tests.
- **Lock enforcement** — locked releases are fully immutable at the model level. No edits, no deletes — from Admin, API, or shell.
- **Soft-delete** — rows can be deactivated without deletion. Deactivating an approved row resets it to `DRAFT` so it must be re-approved before CI sees it again.
- **Auto-discovery** — inherit `VersionedModel` and your model is versioned. No registration needed.
- **Topological FK sort** — models are duplicated in the correct dependency order automatically when branching a release.
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
create_release → architects edit (DRAFT) → lock_release → CI approves → lock_release → deploy_release → ship
```

```bash
# Branch from the previous locked release
python manage.py create_release --release-version v1.1.0 --based-on v1.0.0

# Architects add and edit rows (status=DRAFT by default)

# Need a correction? Unlock is allowed before deployment
python manage.py unlock_release --release-version v1.1.0          # interactive
python manage.py unlock_release --release-version v1.1.0 --force  # CI / automation

# Lock before CI runs — no more edits after this point
python manage.py lock_release --release-version v1.1.0

# CI approves all stable DRAFT rows (FUTURE rows are left untouched)
python manage.py approve_release --release-version v1.1.0

# Run tests against approved data only
pytest

# Lock again if unlocked for corrections, then deploy
python manage.py lock_release --release-version v1.1.0   # skip if already locked
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
| `status` | CharField | Data readiness: `draft` / `future` / `approved` |
| `active` | BooleanField | Soft-delete flag. Inactive rows are invisible to `for_release()` and `approved()` |

**`Release` state fields:**

| Field | Type | Description |
|-------|------|-------------|
| `is_locked` | BooleanField | Immutable — no edits or deletes allowed |
| `deployed` | BooleanField | Deployed to production — unlock is permanently blocked |
| `is_deprecated` | BooleanField | Hidden by default, data preserved |

### Status Flow

```
DRAFT <-> FUTURE -> APPROVED   (APPROVED is one-way — CI only)
```

| Status | Set by | Meaning |
|--------|--------|---------|
| `DRAFT` | Architects | Being worked on |
| `FUTURE` | Architects | Planned but not ready |
| `APPROVED` | CI only | Stable — what tests run against |

### Active / Inactive (Soft-Delete)

```python
row.deactivate()   # sets active=False, resets APPROVED → DRAFT
row.reactivate()   # sets active=True, status stays DRAFT — must re-approve
```

Deactivating an approved row resets its status to `DRAFT`, so it must go through the approval flow again before CI can see it.

### Lock Enforcement

Locked releases are immutable. Any `save()` or `delete()` on a non-approved row raises `ValidationError` — from Admin, API, or shell:

```python
row.save()    # raises ValidationError if release is locked and status != APPROVED
row.delete()  # raises ValidationError if release is locked
```

The only operation permitted on a locked release is `approve()` — this is how CI stamps rows after locking.

---

## 📋 Management Commands

| Command | Description |
|---------|-------------|
| `create_release --release-version v1.0.0` | Create a standalone release (unlocked) |
| `create_release --release-version v1.1.0 --based-on v1.0.0` | Branch from a locked release — copies all rows |
| `lock_release --release-version v1.1.0` | Lock a release (immutable) |
| `approve_release --release-version v1.1.0` | Approve all active DRAFT rows (CI only — FUTURE and inactive untouched) |
| `deploy_release --release-version v1.1.0` | Mark as deployed — permanently blocks unlock |
| `unlock_release --release-version v1.1.0` | Unlock with interactive confirmation (pre-deployment only) |
| `unlock_release --release-version v1.1.0 --force` | Unlock without prompt — safe for CI/automation (pre-deployment only) |
| `deprecate_release --release-version v1.0.0` | Soft-deprecate (data preserved, hidden by default) |
| `deprecate_release --release-version v1.0.0 --undo` | Restore a deprecated release |

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
Product.objects.for_release(release).filter(status="future")
```

---

## 📥 Imports Reference

```python
from django_versioned_models.mixins import VersionedModel, DataStatus
from django_versioned_models.models import Release
from django_versioned_models.services import (
    create_release,
    lock_release,
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
