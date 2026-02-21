"""
Release model — the backbone of the versioning system.

Every versioned row in every table has a FK to Release.
"""

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class Release(models.Model):
    version = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    based_on = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Which release was this branched from?",
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="Locked releases are immutable.",
    )
    is_deprecated = models.BooleanField(
        default=False,
        help_text="Deprecated releases are hidden by default. Data is preserved.",
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    deprecated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "django_versioned_models"
        ordering = ["-created_at"]

    def __str__(self):
        if self.is_deprecated:
            status = "🗄️️"
        elif self.is_locked:
            status = "🔒"
        else:
            status = "✏️"
        return f"{status} {self.version}"

    def lock(self):
        from django.utils import timezone

        self.is_locked = True
        self.locked_at = timezone.now()
        self.save(update_fields=["is_locked", "locked_at"])

    def deprecate(self):
        from django.utils import timezone

        self.is_deprecated = True
        self.deprecated_at = timezone.now()
        self.save(update_fields=["is_deprecated", "deprecated_at"])

    def undeprecate(self):
        self.is_deprecated = False
        self.deprecated_at = None
        self.save(update_fields=["is_deprecated", "deprecated_at"])
