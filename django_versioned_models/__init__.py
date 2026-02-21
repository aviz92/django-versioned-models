"""
django-versioned-models
=======================

Drop-in versioning for Django models.

Quick start:

    # settings.py
    INSTALLED_APPS = ['django_versioned_models', ...]

    # models.py
    from django_versioned_models import VersionedModel

    class MyModel(VersionedModel):
        name = models.CharField(max_length=255)

    # urls.py (optional, DRF required)
    urlpatterns += [path('api/', include('django_versioned_models.urls'))]

That's it. Run migrations and you're ready.
"""

from django_versioned_models.mixins import DataStatus, VersionedModel
from django_versioned_models.services import (
    create_release,
    get_versioned_models,
    get_versioned_models_ordered,
    lock_release,
)

__all__ = [
    "VersionedModel",
    "DataStatus",
    "get_versioned_models",
    "get_versioned_models_ordered",
    "create_release",
    "lock_release",
]

default_app_config = "django_versioned_models.apps.DjangoVersionedModelsConfig"
