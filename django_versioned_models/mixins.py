"""
VersionedModel mixin — inherit this in every model you want versioned.

Status flow:
    DRAFT <-> FUTURE -> APPROVED  (APPROVED is one-way, CI only)

CI runs against: status=APPROVED
Architects edit: status=DRAFT or FUTURE
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class DataStatus(models.TextChoices):
    DRAFT = ("draft", "Draft")
    FUTURE = ("future", "Future")
    APPROVED = ("approved", "Approved")


class VersionedModel(models.Model):
    """
    Abstract base for every versioned entity.

    Usage:
        class Product(VersionedModel):
            name = models.CharField(max_length=255)

    Querying:
        Product.objects.for_release(release)    # all statuses
        Product.objects.approved(release)        # CI uses this
    """

    release = models.ForeignKey(
        "django_versioned_models.Release",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )
    status = models.CharField(
        max_length=20,
        choices=DataStatus,
        default=DataStatus.DRAFT,
        db_index=True,
    )

    class VersionedManager(models.Manager):

        def for_release(self, release: models.Model) -> models.QuerySet:
            """All rows for a release, regardless of status."""
            return self.get_queryset().filter(release=release)

        def approved(self, release: models.Model) -> models.QuerySet:
            """Only approved rows — what CI runs against."""
            return self.get_queryset().filter(
                release=release,
                status=DataStatus.APPROVED,
            )

    objects = VersionedManager()

    # ── Status transitions ────────────────────────────────────────────────────

    def mark_future(self) -> None:
        """DRAFT -> FUTURE. Called by architects."""
        if self.status != DataStatus.DRAFT:
            raise ValidationError(f"Can only move to FUTURE from DRAFT. Current status: {self.status}")
        self.status = DataStatus.FUTURE
        self.save(update_fields=["status"])

    def mark_draft(self) -> None:
        """FUTURE -> DRAFT. Allows rework."""
        if self.status != DataStatus.FUTURE:
            raise ValidationError(f"Can only move back to DRAFT from FUTURE. Current status: {self.status}")
        self.status = DataStatus.DRAFT
        self.save(update_fields=["status"])

    def approve(self) -> None:
        """DRAFT or FUTURE -> APPROVED. One-way. CI only."""
        if self.status == DataStatus.APPROVED:
            raise ValidationError("Row is already approved.")
        self.status = DataStatus.APPROVED
        self.save(update_fields=["status"])

    # ── Lock enforcement ──────────────────────────────────────────────────────

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.release.is_locked and self.status != DataStatus.APPROVED:
            raise ValidationError(
                f"Release {self.release.version} is locked and cannot be modified. "
                f"Create a new release (patch) instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> None:
        if self.release.is_locked:
            raise ValidationError(f"Release {self.release.version} is locked. Cannot delete rows.")
        super().delete(*args, **kwargs)

    class Meta:
        abstract = True
