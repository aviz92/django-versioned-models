# django-versioned-models

![PyPI version](https://img.shields.io/pypi/v/django-versioned-models)
![Python](https://img.shields.io/badge/python->=3.12-blue)
![Development Status](https://img.shields.io/badge/status-stable-green)
![Maintenance](https://img.shields.io/maintenance/yes/2026)
![PyPI](https://img.shields.io/pypi/dm/django-versioned-models)
![License](https://img.shields.io/pypi/l/django-versioned-models)

---

# django-versioned-models
Drop-in versioning for Django models. Every model that inherits from `VersionedModel` gets full release management, data status workflow, and CI integration — automatically.

---

🚀 Features

 - **Release management** - every row in every table is tagged to a release. Branch, lock, patch, and deprecate with simple commands.
 - **Data status workflow** - DRAFT → FUTURE → APPROVED. CI only sees approved rows. Live edits by architects never break tests.
 - **Lock enforcement** - locked releases are immutable at the model level. No edits, no deletes, from anywhere — Admin, API, or shell.
 - **Auto-discovery** - inherit VersionedModel and your model is versioned. No registration needed, no matter how many models.
 - **Topological FK sort** - when copying a release, models are duplicated in the correct dependency order automatically.
 - **Soft deprecation** - old releases are hidden by default but data is always preserved and fully reversible.
 - **Standalone releases** - create a release with no source for bootstrapping a new project or parallel versioning.
 - **CI-ready commands** - create_release, approve_release, lock_release and more, ready to plug into any pipeline.

---

## Installation

```bash
pip install django-versioned-models
```

---

## Quick Start

### 1. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    ...
    'django_versioned_models',
]
```

### 2. Run migrations

```bash
python manage.py migrate
```

### 3. Create your models

```python
from django_versioned_models.mixins import VersionedModel

class MyModel(VersionedModel):
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = [('release', 'name')]  # unique per release, not globally
```

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
# Add data via Admin or API...

python manage.py lock_release --release-version v1.0.0
```

---

## Ongoing Flow

```bash
# Create a new release branched from the previous one
python manage.py create_release --release-version v1.1.0 --based-on v1.0.0

# Architects edit data (status=DRAFT by default)

# CI approves stable rows
python manage.py approve_release --release-version v1.1.0

# Run tests against approved data only
pytest --release-version v1.1.0

# Lock and ship
python manage.py lock_release --release-version v1.1.0

# Bug found after deployment? Create a patch — never modify a locked release
python manage.py create_release --release-version v1.1.1 --based-on v1.1.0
```

---

## How It Works

Every model that inherits from `VersionedModel` gets two fields added automatically:

- `release` — which version this row belongs to
- `status` — data readiness (`draft` / `future` / `approved`)

### Data Status Workflow

```
DRAFT <-> FUTURE -> APPROVED  (one-way, CI only)
```

| Status | Who | Meaning |
|--------|-----|---------|
| `DRAFT` | Architects | Being worked on |
| `FUTURE` | Architects | Planned for a future release |
| `APPROVED` | CI only | Stable — what tests run against |

CI always queries `approved` rows. `DRAFT` and `FUTURE` are invisible to CI — live edits never break tests.

```python
MyModel.objects.approved(release)     # CI — stable rows only
MyModel.objects.for_release(release)  # everyone — all statuses
```

### Lock Enforcement

Locked releases are immutable. Any attempt to save or delete a row in a locked release raises a `ValidationError` — from the Admin, the API, the shell, anywhere.

```python
# This will raise ValidationError if release is locked
my_instance.save()
my_instance.delete()
```

### Auto-Discovery

All models that inherit from `VersionedModel` are discovered automatically on every `create_release`. No manual registration needed. FK dependencies are resolved via topological sort — no ordering required.

---

## Management Commands

| Command | Description |
|---------|-------------|
| `create_release --release-version v1.0.0` | Create a standalone release (unlocked) |
| `create_release --release-version v1.1.0 --based-on v1.0.0` | Branch from a locked release |
| `approve_release --release-version v1.1.0` | Approve all DRAFT rows (CI only — FUTURE untouched) |
| `lock_release --release-version v1.1.0` | Lock a release (immutable) |
| `unlock_release --release-version v1.1.0` | Unlock (only before deployment) |
| `deprecate_release --release-version v1.0.0` | Soft-delete (data preserved, hidden by default) |
| `deprecate_release --release-version v1.0.0 --undo` | Restore a deprecated release |

---

## Querying

```python
from django_versioned_models.models import Release

release = Release.objects.get(version='v1.1.0')

# All rows for a release
MyModel.objects.for_release(release)

# Approved rows only (CI)
MyModel.objects.approved(release)

# Filter by status
MyModel.objects.filter(release=release, status='future')
```

---

## Imports Reference

```python
from django_versioned_models.mixins import VersionedModel, DataStatus
from django_versioned_models.models import Release
from django_versioned_models.services import (
    get_versioned_models,
    get_versioned_models_ordered,
    create_release,
    lock_release,
)
```
