"""
django-versioned-models
=======================

Drop-in versioning for Django models.

Quick start:

    # settings.py
    INSTALLED_APPS = ['django_versioned_models', ...]

    # models.py
    from django_versioned_models.mixins import VersionedModel
    from django_versioned_models.models import Release

    class MyModel(VersionedModel):
        name = models.CharField(max_length=255)
"""

default_app_config = 'django_versioned_models.apps.DjangoVersionedModelsConfig'
