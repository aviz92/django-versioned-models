# Django Commands
This document provides a list of common Django management commands that can be used to perform various tasks in a Django project.

## Common Django Commands

### App Management
- `django-admin startproject <project_name>`: Creates a new Django project with the specified name.
- `uv run python manage.py startapp <app_name>`: Creates a new Django app with the specified name.
- `uv run python manage.py startapp <app_name> <sub_folder>/<app_name>`: Creates a new Django app with the specified name under the specified sub-folder.
- `uv run python manage.py runserver`: Starts the development server.

### Database and Migrations
- `uv run python manage.py makemigrations`: Creates new migrations based on the changes detected in models.
- `uv run python manage.py migrate`: Applies the migrations to the database.
- `uv run python manage.py createsuperuser`: Creates a new superuser for the admin interface.

### Data Management
- `uv run python manage.py flush`: Resets the database by removing all data and reapplying migrations.
- `uv run python manage.py loaddata <fixture_name>`: Loads data from a fixture file into the database.
- `uv run python manage.py dumpdata <app_name>.<model_name>`: Exports data from the specified model into a JSON format.

### Utility Commands
- `uv run python manage.py check`: Checks the entire Django project for potential issues without making database migrations.
- `uv run python manage.py dbshell`: Opens the database shell for the configured database.
- `uv run python manage.py diffsettings`: Displays the differences between the current settings and Django's default settings.
- `uv run python manage.py inspectdb`: Generates model code by introspecting the database tables.

---

### Custom Commands

#### create_release:
- `uv run python manage.py create_release --release-version v1.1.1 --based-on v1.0.0`: Creates a new release based on the specified version.

#### lock_release:
- `uv run python manage.py lock_release --release-version v1.1.0`: Locks the specified release version to prevent further modifications.

#### unlock_release:
- `uv run python manage.py unlock_release --release-version v1.1.0`: Unlocks the specified release version to allow modifications.

#### delete_release:
- `uv run python manage.py delete_release --release-version v1.1.0`: Permanently deletes the specified release and all its versioned rows, after typing the version to confirm. Not allowed for deployed releases. Releases branched from it are kept, but their `based_on` is cleared (a warning lists them).
- `uv run python manage.py delete_release --release-version v1.1.0 --dry-run`: Shows how many objects per model would be deleted, without deleting anything.
- `uv run python manage.py delete_release --release-version v1.1.0 --force`: Deletes without the confirmation prompt (for CI/automation).

#### restore_releases:
- `uv run python manage.py restore_releases dump.json`: Restores a full dump (from `dumpdata`) that contains locked or deployed releases — plain `loaddata` refuses to write those. Verifies afterwards that no reference crosses releases and rolls the whole load back if one does.

#### check_release_isolation:
- `uv run python manage.py check_release_isolation`: Read-only scan for references that cross releases (a row pointing to a versioned row of another release). Lists each offending field with example row ids and exits with an error if any are found — run it after upgrading or in CI.

#### approve_release:
- `uv run python manage.py approve_release --release-version v1.1.0`: Approves the specified release version, indicating that it has passed all necessary checks and is ready for deployment.
- `uv run python manage.py approve_release --release-version v1.1.0 --only-future`: Approves the specified release version, but only if it is a future release (i.e., its version number is greater than the current version). This can be used to ensure that only upcoming releases are approved, while past releases remain unaffected.

#### deprecate_release:
- `uv run python manage.py deprecate_release --release-version v1.0.0`: Deprecates the specified release version, indicating that it is no longer recommended for use and may be removed in the future.
- `uv run python manage.py deprecate_release --release-version v1.0.0 --undo`: Undeprecates the specified release version, reversing the deprecation status and making it recommended for use again. This can be useful if a previously deprecated release has been updated or if the deprecation was made in error.
