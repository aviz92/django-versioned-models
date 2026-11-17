from django.apps import AppConfig


class DjangoVersionedModelsConfig(AppConfig):
    name = "django_versioned_models"
    verbose_name = "Django Versioned Models"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # pylint: disable=C0415
        from django_versioned_models.mixins import connect_cascade_guards
        from django_versioned_models.services import get_versioned_models

        connect_cascade_guards(get_versioned_models())
