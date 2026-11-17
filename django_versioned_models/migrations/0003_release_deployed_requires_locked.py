from django.apps.registry import Apps
from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models import F, Q
from django.db.models.functions import Coalesce, Now


def relock_deployed_releases(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Re-lock any deployed release that was unlocked, so the new constraint can be added."""
    Release = apps.get_model("django_versioned_models", "Release")  # pylint: disable=C0103
    Release.objects.filter(deployed=True, is_locked=False).update(
        is_locked=True,
        locked_at=Coalesce(F("locked_at"), F("deployed_at"), Now()),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("django_versioned_models", "0002_release_deployed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(relock_deployed_releases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="release",
            constraint=models.CheckConstraint(
                condition=Q(deployed=False) | Q(is_locked=True),
                name="release_deployed_requires_locked",
                violation_error_message="A deployed release must be locked.",
            ),
        ),
    ]
