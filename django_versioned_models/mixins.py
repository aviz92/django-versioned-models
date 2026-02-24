"""
VersionedModel mixin — inherit this in every model you want versioned.

Status flow:
    DRAFT <-> FUTURE -> APPROVED  (APPROVED is one-way, CI only)

Active flow:
    active=False → status resets to DRAFT automatically
    active=True  → stays DRAFT, must go through approval again

CI runs against: status=APPROVED + active=True
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
        Product.objects.for_release(release)    # active rows, all statuses — architect GUI view
        Product.objects.approved(release)        # CI uses this (APPROVED + active only)
        Product.objects.all_rows(release)        # everything including inactive — copy/audit only
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
    active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Inactive rows are soft-deleted. "
            "Deactivating resets status to DRAFT — "
            "row must be explicitly re-approved before CI sees it again."
        ),
    )

    class VersionedManager(models.Manager):

        def for_release(self, release: models.Model) -> models.QuerySet:
            """
            Active rows for a release, all statuses.
            Use this for architect-facing GUI views — shows exactly what's alive in this release.
            """
            return self.get_queryset().filter(release=release)

        def approved(self, release: models.Model) -> models.QuerySet:
            """Only approved + active rows — what CI runs against."""
            return self.get_queryset().filter(
                release=release,
                status=DataStatus.APPROVED,
                active=True,
            )

        def all_rows(self, release):
            """
            All rows including inactive — for copying between releases and admin/audit use.
            Do not use for business logic.
            """
            return self.get_queryset().filter(release=release)

    objects = VersionedManager()

    # ── Active / inactive ─────────────────────────────────────────────────────

    def deactivate(self) -> None:
        """
        Soft-delete this row.
        If the row was APPROVED, status is reset to DRAFT —
        it must be explicitly re-approved before CI sees it again.
        """
        if not self.active:
            raise ValidationError("Row is already inactive.")
        self.active = False
        if self.status == DataStatus.APPROVED:
            self.status = DataStatus.DRAFT
        self.save(update_fields=["active", "status"])

    def reactivate(self) -> None:
        """
        Restore a deactivated row.
        Status stays DRAFT — must go through the approval flow again.
        """
        if self.active:
            raise ValidationError("Row is already active.")
        self.active = True
        self.save(update_fields=["active"])

    # ── Status transitions ────────────────────────────────────────────────────

    def mark_future(self) -> None:
        """DRAFT -> FUTURE. Called by architects."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status != DataStatus.DRAFT:
            raise ValidationError(f"Can only move to FUTURE from DRAFT. Current status: {self.status}")
        self.status = DataStatus.FUTURE
        self.save(update_fields=["status"])

    def mark_draft(self) -> None:
        """FUTURE -> DRAFT. Allows rework."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status != DataStatus.FUTURE:
            raise ValidationError(f"Can only move back to DRAFT from FUTURE. Current status: {self.status}")
        self.status = DataStatus.DRAFT
        self.save(update_fields=["status"])

    def approve(self) -> None:
        """DRAFT or FUTURE -> APPROVED. One-way. CI only."""
        if not self.active:
            raise ValidationError("Cannot approve an inactive row.")
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
