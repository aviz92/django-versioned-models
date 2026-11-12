"""
VersionedModel mixin — inherit this in every model you want versioned.

Status flow:
    DRAFT <-> FUTURE_DEVELOPMENT -> APPROVED  (APPROVED is one-way, CI only)
    DRAFT <-> FUTURE_DEPRECATION -> APPROVED  (APPROVED is one-way, CI only)

Active flow:
    active=False → status resets to DRAFT automatically
    active=True  → stays DRAFT, must go through approval again

CI runs against: status=APPROVED + active=True
Architects edit: status=DRAFT, FUTURE_DEVELOPMENT, or FUTURE_DEPRECATION

Lock flow:
    approve_release -> lock_release -> deploy_release
    Rows in a locked or deployed release are fully immutable — no save, delete,
    approve, or QuerySet update/delete/bulk_create/bulk_update.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

_FROZEN_RELEASE_Q = Q(release__is_locked=True) | Q(release__deployed=True)


def _raise_if_releases_locked(release_ids: Iterable[int | None], action: str) -> None:
    """
    Raise ValidationError if any of the given releases is locked or deployed.

    Always reads lock state from the DB — a cached Release instance may be stale.
    """
    from django_versioned_models.models import Release  # pylint: disable=C0415

    if not (ids := {pk for pk in release_ids if pk is not None}):
        return
    locked = sorted(
        Release.objects.filter(pk__in=ids)
        .filter(Q(is_locked=True) | Q(deployed=True))
        .values_list("version", flat=True)
    )
    if locked:
        raise ValidationError(
            f"Release {', '.join(locked)} is locked and cannot be modified ({action}). "
            "Create a new release (patch) instead."
        )


def _release_id_from_kwargs(kwargs: dict[str, Any]) -> int | None:
    """Extract a target release id from QuerySet.update() kwargs, if one is being set."""
    if "release_id" in kwargs:
        return kwargs["release_id"]
    release = kwargs.get("release")
    return getattr(release, "pk", release)


class VersionedQuerySet(models.QuerySet):
    """QuerySet that refuses bulk writes touching rows of a locked or deployed release."""

    def for_release(self, release: models.Model) -> "VersionedQuerySet":
        """
        Active rows for a release, all statuses.
        Use this for architect-facing GUI views — shows exactly what's alive in this release.
        """
        return self.filter(release=release, active=True)

    def approved(self, release: models.Model) -> "VersionedQuerySet":
        """Only approved + active rows — what CI runs against."""
        return self.filter(release=release, status=DataStatus.APPROVED, active=True)

    def all_rows(self, release: models.Model) -> "VersionedQuerySet":
        """
        All rows including inactive — for copying between releases and admin/audit use.
        Do not use for business logic.
        """
        return self.filter(release=release)

    def _raise_if_touches_locked_release(self, action: str) -> None:
        if self.filter(_FROZEN_RELEASE_Q).exists():
            raise ValidationError(
                f"QuerySet {action} touches rows of a locked release. Create a new release (patch) instead."
            )

    def update(self, **kwargs: Any) -> int:
        self._raise_if_touches_locked_release("update")
        _raise_if_releases_locked([_release_id_from_kwargs(kwargs)], "update")
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        self._raise_if_touches_locked_release("delete")
        return super().delete()

    def bulk_create(self, objs: Iterable[models.Model], *args: Any, **kwargs: Any) -> list[models.Model]:
        objs = list(objs)
        _raise_if_releases_locked((obj.release_id for obj in objs), "bulk_create")
        return super().bulk_create(objs, *args, **kwargs)

    def bulk_update(self, objs: Iterable[models.Model], fields: Sequence[str], *args: Any, **kwargs: Any) -> int:
        objs = list(objs)
        # Check stored release (rows can't leave a locked release) and target release (can't enter one).
        stored = self.model._base_manager.filter(pk__in=[obj.pk for obj in objs])  # pylint: disable=W0212
        if stored.filter(_FROZEN_RELEASE_Q).exists():
            raise ValidationError(
                "QuerySet bulk_update touches rows of a locked release. Create a new release (patch) instead."
            )
        _raise_if_releases_locked((obj.release_id for obj in objs), "bulk_update")
        return super().bulk_update(objs, fields, *args, **kwargs)


class DataStatus(models.TextChoices):
    DRAFT = ("draft", "Draft")
    FUTURE_DEVELOPMENT = ("future_development", "Future development")
    FUTURE_DEPRECATION = ("future_deprecation", "Future deprecation")
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

    class VersionedManager(models.Manager.from_queryset(VersionedQuerySet)):  # type: ignore[misc]
        """Exposes for_release / approved / all_rows and the lock-guarded bulk operations."""

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

    def mark_future_deprecation(self) -> None:
        """DRAFT -> FUTURE_DEPRECATION. Called by architects."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status != DataStatus.DRAFT:
            raise ValidationError(f"Can only move to FUTURE_DEPRECATION from DRAFT. Current status: {self.status}")
        self.status = DataStatus.FUTURE_DEPRECATION
        self.save(update_fields=["status"])

    def mark_draft(self) -> None:
        """FUTURE_DEVELOPMENT or FUTURE_DEPRECATION -> DRAFT. Allows rework."""
        if not self.active:
            raise ValidationError("Cannot change status of an inactive row.")
        if self.status not in (DataStatus.FUTURE_DEVELOPMENT, DataStatus.FUTURE_DEPRECATION):
            raise ValidationError(
                f"Can only move back to DRAFT from FUTURE_DEVELOPMENT or FUTURE_DEPRECATION. "
                f"Current status: {self.status}"
            )
        self.status = DataStatus.DRAFT
        self.save(update_fields=["status"])

    def approve(self) -> None:
        """DRAFT, FUTURE_DEVELOPMENT, or FUTURE_DEPRECATION -> APPROVED. One-way. CI only."""
        if not self.active:
            raise ValidationError("Cannot approve an inactive row.")
        if self.status == DataStatus.APPROVED:
            raise ValidationError("Row is already approved.")
        self.status = DataStatus.APPROVED
        self.save(update_fields=["status"])

    # ── Lock enforcement ──────────────────────────────────────────────────────

    def _affected_release_ids(self) -> set[int | None]:
        """
        Releases a write to this row touches: the target release and, for an existing row,
        the release it is currently stored under (so rows can't be moved out of a locked release).
        """
        release_ids = {self.release_id}
        if not self._state.adding:
            # pylint: disable=W0212
            release_ids.add(type(self)._base_manager.filter(pk=self.pk).values_list("release_id", flat=True).first())
        return release_ids

    def save(self, *args: Any, **kwargs: Any) -> None:
        _raise_if_releases_locked(self._affected_release_ids(), "save")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _raise_if_releases_locked(self._affected_release_ids(), "delete")
        return super().delete(*args, **kwargs)

    class Meta:
        abstract = True
        indexes = [
            models.Index(
                fields=["release", "status", "active"],
                name="%(app_label)s_%(class)s_rel_sta_act_idx",
            ),
        ]
