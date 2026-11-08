# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
