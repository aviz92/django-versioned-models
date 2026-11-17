"""
Release model — the backbone of the versioning system.

Every versioned row in every table has a FK to Release.

Deployed releases are guarded at the model level, not only in the services and commands:
their identity and lock fields cannot change (save, QuerySet.update, bulk_update) and they
cannot be deleted (delete, QuerySet.delete). A DB constraint enforces deployed => locked.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = get_user_model()

# Fields of a deployed release that can never change. Deprecation, description and based_on stay editable.
DEPLOYED_FROZEN_FIELDS = ("version", "is_locked", "locked_at", "deployed", "deployed_at")


def _deployed_versions(queryset: models.QuerySet) -> list[str]:
    return sorted(queryset.filter(deployed=True).values_list("version", flat=True))


class ReleaseQuerySet(models.QuerySet):
    """QuerySet that refuses bulk deletes of deployed releases and bulk changes to their frozen fields."""

    def delete(self) -> tuple[int, dict[str, int]]:
        if deployed := _deployed_versions(self):
            raise ValidationError(f"Release {', '.join(deployed)} is deployed and cannot be deleted.")
        return super().delete()

    def update(self, **kwargs: Any) -> int:
        if (frozen := sorted(set(DEPLOYED_FROZEN_FIELDS) & kwargs.keys())) and (deployed := _deployed_versions(self)):
            raise ValidationError(f"Release {', '.join(deployed)} is deployed — cannot change {', '.join(frozen)}.")
        return super().update(**kwargs)


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
    deployed = models.BooleanField(
        default=False,
        help_text="Deployed releases cannot be unlocked. Must be locked before deploying.",
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
    deployed_at = models.DateTimeField(null=True, blank=True)

    objects = ReleaseQuerySet.as_manager()

    class Meta:
        app_label = "django_versioned_models"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(deployed=False) | Q(is_locked=True),
                name="release_deployed_requires_locked",
                violation_error_message="A deployed release must be locked.",
            ),
        ]

    def __str__(self) -> str:
        if self.is_deprecated:
            status = "🗄️️"
        elif self.deployed:
            status = "🔒🚀"
        elif self.is_locked:
            status = "🔒"
        else:
            status = "✏️"
        return f"{status} {self.version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """
        Refuse changes to the frozen fields of a deployed release.

        Compares against the stored row, not this instance, so a stale instance can't bypass the guard.
        With update_fields, only the fields actually being written are checked.
        """
        if not self._state.adding and self.pk is not None:
            fields = set(DEPLOYED_FROZEN_FIELDS)
            if (update_fields := kwargs.get("update_fields")) is not None:
                fields &= set(update_fields)
            stored = type(self)._base_manager.filter(pk=self.pk, deployed=True).values(*DEPLOYED_FROZEN_FIELDS).first()
            if stored and (changed := sorted(f for f in fields if getattr(self, f) != stored[f])):
                raise ValidationError(
                    f'Release "{stored["version"]}" is deployed — cannot change {", ".join(changed)}. '
                    f"Create a patch release instead."
                )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Refuse to delete a deployed release (read from the DB — a stale instance can't bypass it)."""
        if self.pk is not None and type(self)._base_manager.filter(pk=self.pk, deployed=True).exists():
            raise ValidationError(f'Release "{self.version}" is deployed and cannot be deleted.')
        return super().delete(*args, **kwargs)

    def lock(self) -> None:
        self.is_locked = True
        self.locked_at = timezone.now()
        self.save(update_fields=["is_locked", "locked_at"])

    def deploy(self) -> None:
        if not self.is_locked:
            raise ValueError(f'Release "{self.version}" must be locked before it can be deployed.')
        self.deployed = True
        self.deployed_at = timezone.now()
        self.save(update_fields=["deployed", "deployed_at"])

    def deprecate(self) -> None:
        self.is_deprecated = True
        self.deprecated_at = timezone.now()
        self.save(update_fields=["is_deprecated", "deprecated_at"])

    def undeprecate(self) -> None:
        self.is_deprecated = False
        self.deprecated_at = None
        self.save(update_fields=["is_deprecated", "deprecated_at"])
