# django-versioned-models

[![PyPI version](https://img.shields.io/pypi/v/django-versioned-models)](https://pypi.org/project/django-versioned-models/)
[![Python](https://img.shields.io/badge/python-%3E=3.12-blue)](https://img.shields.io/badge/python-%3E=3.12-blue)
[![License](https://img.shields.io/pypi/l/django-versioned-models)](https://img.shields.io/pypi/l/django-versioned-models)

Drop-in versioning for Django models. Every model that inherits from `VersionedModel` gets full release management, data status workflow, and CI integration — automatically.

---

## Installation

```bash
pip install django-versioned-models

# With DRF support
pip install django-versioned-models[drf]
```

---

## Quick Start

**1. Add to INSTALLED_APPS:**
```python
INSTALLED_APPS = [
    ...
    'django_versioned_models',
    'rest_framework',           # optional, for API support
    'rest_framework.authtoken', # optional, for token auth
]
```

**2. Inherit VersionedModel:**
```python
from django_versioned_models import VersionedModel

class MyModel(VersionedModel):
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = [('release', 'name')]
```

**3. Add URLs (optional, DRF required):**
```python
urlpatterns = [
    path('api/', include('django_versioned_models.urls')),
    ...
]
```

**4. Run migrations:**
```bash
python manage.py migrate
python manage.py setup_groups
```

That's it.

---

## How It Works
Every versioned row has two key fields added automatically:

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

CI always queries `approved` rows. DRAFT and FUTURE are invisible to CI.

```python
MyModel.objects.approved(release)     # CI — stable only
MyModel.objects.for_release(release)  # everyone — all statuses
```

---

## Management Commands
```bash
# Create a new release branched from an existing locked one
python manage.py create_release --release-version v1.1.0 --based-on v1.0.0

# Approve all DRAFT rows (CI runs this — FUTURE rows untouched)
python manage.py approve_release --release-version v1.1.0

# Lock a release (immutable after this)
python manage.py lock_release --release-version v1.1.0

# Unlock (only before deployment)
python manage.py unlock_release --release-version v1.1.0

# Soft-delete a release (data preserved, hidden from API)
python manage.py deprecate_release --release-version v1.0.0
python manage.py deprecate_release --release-version v1.0.0 --undo

# Create default permission groups (run once, then again when adding new models)
python manage.py setup_groups
```

### Typical CI Flow
```
create_release --release-version v1.1.0 --based-on v1.0.0
      ↓
architects edit data (status=DRAFT by default)
      ↓
approve_release --release-version v1.1.0
      ↓
pytest --release-version v1.1.0   (runs against APPROVED only)
      ↓
lock_release --release-version v1.1.0
      ↓
bug found? → create_release --release-version v1.1.1 --based-on v1.1.0
```

---

## API (DRF)
```
GET  /api/releases/                          # active releases
GET  /api/releases/?include_deprecated=true  # include deprecated
POST /api/releases/<id>/lock/                # lock (admin only)
POST /api/auth/token/                        # get auth token
```

All versioned endpoints accept:
```
?version=v1.1.0           # filter by release
?status=approved          # filter by status
```

### Permissions
Four groups are created by `setup_groups`:

| Group | GET | POST | PUT/PATCH | DELETE |
|-------|-----|------|-----------|--------|
| `viewers` | ✅ | ❌ | ❌ | ❌ |
| `editors` | ✅ | ❌ | ✅ | ❌ |
| `creators` | ✅ | ✅ | ✅ | ❌ |
| `admins` | ✅ | ✅ | ✅ | ✅ |

Assign users to groups in Django Admin.

### Base ViewSet
```python
from django_versioned_models.views import VersionedViewSet

class MyModelViewSet(VersionedViewSet):
    queryset = MyModel.objects.select_related('release')
    serializer_class = MyModelSerializer
```

Permissions and version filtering come for free.

---

## Admin
```python
from django_versioned_models.admin import VersionedModelAdmin

@admin.register(MyModel)
class MyModelAdmin(VersionedModelAdmin):
    list_display = ('name', 'release', 'status')
```

`release` and `status` fields are injected into the form automatically.

---

## Adding a New Model
1. Inherit from `VersionedModel`
2. Run `makemigrations` and `migrate`
3. Run `setup_groups` to update permissions

Done. Auto-discovery handles the rest — no manual registration.

---

## License
MIT
