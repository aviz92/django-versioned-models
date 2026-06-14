"""
VersionedModel mixin — inherit this in every model you want versioned.

Status flow:
    DRAFT <-> FUTURE_DEVELOPMENT -> APPROVED  (APPROVED is one-way, CI only)
    DRAFT <-> FEATURE_DEPRECATION -> APPROVED  (APPROVED is one-way, CI only)

Active flow:
    active=False → status resets to DRAFT automatically
    active=True  → stays DRAFT, must go through approval again

CI runs against: status=APPROVED + active=True
Architects edit: status=DRAFT, FUTURE_DEVELOPMENT, or FEATURE_DEPRECATION
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class DataStatus(models.TextChoices):
    DRAFT = ("draft", "Draft")
    FUTURE_DEVELOPMENT = ("future_development", "Future development")
    FEATURE_DEPRECATION = ("feature_deprecation", "Feature deprecation")
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
            return self.get_queryset().filter(release=release, active=True)

        def approved(self, release: models.Model) -> models.QuerySet:
            """Only approved + active rows — what CI runs against."""
            return self.get_queryset().filter(
                release=release,
                status=DataStatus.APPROVED,
                active=True,
            )

        def all_rows(self, release: models.Model) -> models.QuerySet:
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

    def mark_future_development(self) -> None:
        """DRAFT -> FUTURE_DEVELOPMENT. Called by architects."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status != DataStatus.DRAFT:
            raise ValidationError(f"Can only move to FUTURE_DEVELOPMENT from DRAFT. Current status: {self.status}")
        self.status = DataStatus.FUTURE_DEVELOPMENT
        self.save(update_fields=["status"])

    def mark_feature_deprecation(self) -> None:
        """DRAFT -> FEATURE_DEPRECATION. Called by architects."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status != DataStatus.DRAFT:
            raise ValidationError(f"Can only move to FEATURE_DEPRECATION from DRAFT. Current status: {self.status}")
        self.status = DataStatus.FEATURE_DEPRECATION
        self.save(update_fields=["status"])

    def mark_draft(self) -> None:
        """FUTURE_DEVELOPMENT or FEATURE_DEPRECATION -> DRAFT. Allows rework."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status not in (DataStatus.FUTURE_DEVELOPMENT, DataStatus.FEATURE_DEPRECATION):
            raise ValidationError(
                f"Can only move back to DRAFT from FUTURE_DEVELOPMENT or FEATURE_DEPRECATION. "
                f"Current status: {self.status}"
            )
        self.status = DataStatus.DRAFT
        self.save(update_fields=["status"])

    def approve(self) -> None:
        """DRAFT, FUTURE_DEVELOPMENT, or FEATURE_DEPRECATION -> APPROVED. One-way. CI only."""
        if not self.active:
            raise ValidationError("Cannot approve an inactive row.")
        if self.status == DataStatus.APPROVED:
            raise ValidationError("Row is already approved.")
        self.status = DataStatus.APPROVED
        self.save(update_fields=["status"])

    # ── Lock enforcement ──────────────────────────────────────────────────────

    def _is_release_locked(self) -> bool:
        # Use Django's FK instance cache when available (e.g. after select_related or
        # direct assignment). Falls back to a single-column DB query to avoid SELECT *.
        # Django stores FK instances via field.set_cached_value — must use get_cached_value,
        # not __dict__["release"], because the cache key is "_release_cache", not "release".
        release_field = self.__class__._meta.get_field("release")  # pylint: disable=W0212
        try:
            cached = release_field.get_cached_value(self)
            return cached.is_locked
        except KeyError:
            pass
        from django_versioned_models.models import Release  # pylint: disable=C0415

        return Release.objects.filter(pk=self.release_id).values_list("is_locked", flat=True).first() or False

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._is_release_locked() and self.status != DataStatus.APPROVED:
            raise ValidationError(
                f"Release {self.release_id} is locked and cannot be modified. " f"Create a new release (patch) instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> None:
        if self._is_release_locked():
            raise ValidationError(f"Release {self.release_id} is locked. Cannot delete rows.")
        super().delete(*args, **kwargs)

    class Meta:
        abstract = True
        indexes = [
            models.Index(
                fields=["release", "status", "active"],
                name="%(app_label)s_%(class)s_rel_sta_act_idx",
            ),
        ]
