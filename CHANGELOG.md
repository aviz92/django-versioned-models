# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
