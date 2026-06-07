from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_versioned_models", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="release",
            name="deployed",
            field=models.BooleanField(
                default=False,
                help_text="Deployed releases cannot be unlocked. Must be locked before deploying.",
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="deployed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
