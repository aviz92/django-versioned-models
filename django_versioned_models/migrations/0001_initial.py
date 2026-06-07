import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Release",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.CharField(max_length=50, unique=True)),
                ("description", models.TextField(blank=True)),
                (
                    "is_locked",
                    models.BooleanField(default=False, help_text="Locked releases are immutable."),
                ),
                (
                    "is_deprecated",
                    models.BooleanField(
                        default=False,
                        help_text="Deprecated releases are hidden by default. Data is preserved.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("deprecated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "based_on",
                    models.ForeignKey(
                        blank=True,
                        help_text="Which release was this branched from?",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="django_versioned_models.release",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "app_label": "django_versioned_models",
            },
        ),
    ]
