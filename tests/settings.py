SECRET_KEY = "test-secret-key-not-for-production"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_versioned_models",
    "tests.testapp",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Skip migration files for the test app — Django creates tables directly
MIGRATION_MODULES = {
    "testapp": None,
}

USE_TZ = True
