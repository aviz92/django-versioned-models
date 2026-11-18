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
    approve, or QuerySet update/delete/bulk_create/bulk_update. Deleting an object
    that locked rows point to is refused too when the delete would cascade into them
    (CASCADE removes them; SET_NULL / SET_DEFAULT / SET() rewrites them).
"""

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.signals import m2m_changed, pre_delete, pre_save

_FROZEN_RELEASE_Q = Q(release__is_locked=True) | Q(release__deployed=True)


def _raise_if_releases_locked(release_ids: Iterable[int | None], action: str) -> None:
    """
    Raise ValidationError if any of the given releases is locked or deployed.

    Always reads lock state from the DB — a cached Release instance may be stale.
    """

    if locked := _locked_versions(release_ids):
        raise ValidationError(_locked_message(locked, action))


def _locked_versions(release_ids: Iterable[int | None]) -> list[str]:
    """Versions of the given releases that are locked or deployed, read from the DB."""
    from django_versioned_models.models import Release  # pylint: disable=C0415

    if not (ids := {pk for pk in release_ids if pk is not None}):
        return []
    if (building := _release_being_built.get()) is not None and ids == {building}:
        return []  # the release create_release is filling right now — unlocked and not visible to anyone else
    return sorted(
        Release.objects.filter(pk__in=ids)
        .filter(Q(is_locked=True) | Q(deployed=True))
        .values_list("version", flat=True)
    )


def _locked_message(locked: list[str], action: str) -> str:
    return (
        f"Release {', '.join(locked)} is locked and cannot be modified ({action}). "
        "Create a new release (patch) instead."
    )


def _release_id_from_kwargs(kwargs: dict[str, Any]) -> int | None:
    """Extract a target release id from QuerySet.update() kwargs, if one is being set."""
    if "release_id" in kwargs:
        return kwargs["release_id"]
    release = kwargs.get("release")
    return getattr(release, "pk", release)


def _versioned_fks(model: type[models.Model]) -> list[Any]:
    """Concrete FK / one-to-one fields of a model that point to a versioned model (the release FK excluded)."""
    return [
        f
        for f in model._meta.concrete_fields  # pylint: disable=W0212
        if f.is_relation
        and (f.many_to_one or f.one_to_one)
        and f.name != "release"
        and issubclass(f.related_model, VersionedModel)
    ]


def _isolation_error(model: type[models.Model], field_name: str, target: type[models.Model], target_pk: Any) -> str:
    return (
        f"{model.__name__}.{field_name} must point to a row in the same release, but "
        f"{target.__name__} {target_pk} belongs to another release. Releases are isolated — "
        f"point to the copy of that row in this release instead."
    )


def _raise_if_cross_release(objs: Sequence[models.Model], fields: Iterable[str] | None = None) -> None:
    """
    Raise ValidationError if any FK / one-to-one of `objs` points to a versioned row of another release.
    `fields` limits the check to the fields being written (names or attnames); None checks them all.
    """
    if not objs:
        return
    model = type(objs[0])
    if (building := _release_being_built.get()) is not None and all(o.release_id == building for o in objs):
        return  # create_release remaps every reference into the release it is building
    wanted_fields = None if fields is None else set(fields)
    for field in _versioned_fks(model):
        if wanted_fields is not None and not {field.name, field.attname} & wanted_fields:
            continue
        pairs = {(getattr(o, field.attname), o.release_id) for o in objs if getattr(o, field.attname) is not None}
        if not pairs:
            continue
        base_manager = field.related_model._base_manager  # pylint: disable=W0212
        target_release = dict(base_manager.filter(pk__in={t for t, _ in pairs}).values_list("pk", "release_id"))
        for target_pk, release_id in sorted(pairs, key=str):
            if target_pk in target_release and target_release[target_pk] != release_id:
                raise ValidationError(_isolation_error(model, field.name, field.related_model, target_pk))


_MOVE_ERROR = (
    "Rows cannot move between releases — references to and from them would cross releases. "
    "Create the row in the target release instead."
)


class VersionedQuerySet(models.QuerySet):
    """
    QuerySet that refuses bulk writes touching rows of a locked or deployed release, writes that would
    point a row at another release, and moving rows between releases.
    """

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
        if ("release" in kwargs or "release_id" in kwargs) and self.exclude(
            release_id=_release_id_from_kwargs(kwargs)
        ).exists():
            raise ValidationError(_MOVE_ERROR)
        self._raise_if_update_crosses_releases(kwargs)
        return super().update(**kwargs)

    def _raise_if_update_crosses_releases(self, kwargs: dict[str, Any]) -> None:
        for field in _versioned_fks(self.model):
            key = field.name if field.name in kwargs else field.attname if field.attname in kwargs else None
            if key is None or (value := kwargs[key]) is None or hasattr(value, "resolve_expression"):
                continue
            target_pk = getattr(value, "pk", value)
            base_manager = field.related_model._base_manager  # pylint: disable=W0212
            target_release = base_manager.filter(pk=target_pk).values_list("release_id", flat=True).first()
            if target_release is not None and self.exclude(release_id=target_release).exists():
                raise ValidationError(_isolation_error(self.model, field.name, field.related_model, target_pk))

    def delete(self) -> tuple[int, dict[str, int]]:
        self._raise_if_touches_locked_release("delete")
        return super().delete()

    def bulk_create(self, objs: Iterable[models.Model], *args: Any, **kwargs: Any) -> list[models.Model]:
        objs = list(objs)
        _raise_if_releases_locked((obj.release_id for obj in objs), "bulk_create")
        _raise_if_cross_release(objs)
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
        stored_release = dict(stored.values_list("pk", "release_id"))
        if any(stored_release.get(obj.pk, obj.release_id) != obj.release_id for obj in objs):
            raise ValidationError(_MOVE_ERROR)
        _raise_if_cross_release(objs, fields)
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

    # ── Validation (forms, admin, full_clean) ────────────────────────────────

    def full_clean(self, exclude: Iterable[str] | None = None, validate_unique: bool = True, **kwargs: Any) -> None:
        # Remember which fields the caller (e.g. a ModelForm) leaves out, so clean() can attach each error
        # to a field the form actually shows — or to the form as a whole.
        self._full_clean_exclude = set(exclude or ())  # pylint: disable=W0201
        try:
            super().full_clean(exclude=exclude, validate_unique=validate_unique, **kwargs)
        finally:
            del self._full_clean_exclude

    def clean(self) -> None:
        """
        Run the release rules before anything is written, so a form shows them as errors instead of the
        save failing: the row's release must not be locked or deployed, rows can't move between releases,
        and every FK / one-to-one to a versioned model must point into the row's own release.
        Subclasses overriding clean() must call super().clean().
        """
        super().clean()
        if errors := self.release_errors(getattr(self, "_full_clean_exclude", set())):
            raise ValidationError(errors)

    def release_errors(self, exclude: Iterable[str] = (), stored_from_db: bool = False) -> dict[str, list[str]]:
        """
        The release-rule violations this row would hit if saved now, keyed by field name — or by
        NON_FIELD_ERRORS for a field in `exclude` (not shown on the form). Empty if the row can be saved.

        `stored_from_db` reads the stored row by primary key even for an instance Django considers new —
        rows loaded from a fixture are, even when they overwrite an existing row.
        """
        exclude = set(exclude)
        errors: dict[str, list[str]] = {}

        def add(field: str, message: str) -> None:
            errors.setdefault(NON_FIELD_ERRORS if field in exclude else field, []).append(message)

        if self.release_id is None:
            return errors
        stored_release = None
        if self.pk is not None and (stored_from_db or not self._state.adding):
            # pylint: disable=W0212
            stored_release = type(self)._base_manager.filter(pk=self.pk).values_list("release_id", flat=True).first()
        if locked := _locked_versions([stored_release]):
            errors.setdefault(NON_FIELD_ERRORS, []).append(_locked_message(locked, "save"))
            return errors
        if locked := _locked_versions([self.release_id]):
            add("release", _locked_message(locked, "save"))
            return errors
        if stored_release is not None and stored_release != self.release_id:
            add("release", _MOVE_ERROR)
            return errors
        for field in _versioned_fks(type(self)):
            if (target_pk := getattr(self, field.attname)) is None:
                continue
            base_manager = field.related_model._base_manager  # pylint: disable=W0212
            target_release = base_manager.filter(pk=target_pk).values_list("release_id", flat=True).first()
            if target_release is not None and target_release != self.release_id:
                add(field.name, _isolation_error(type(self), field.name, field.related_model, target_pk))
        return errors

    def save(self, *args: Any, **kwargs: Any) -> None:
        stored_release = None
        if not self._state.adding:
            # pylint: disable=W0212
            stored_release = type(self)._base_manager.filter(pk=self.pk).values_list("release_id", flat=True).first()
        _raise_if_releases_locked({self.release_id, stored_release}, "save")
        if stored_release is not None and stored_release != self.release_id:
            raise ValidationError(_MOVE_ERROR)
        _raise_if_cross_release([self], kwargs.get("update_fields"))
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


# ── Cascade guard ─────────────────────────────────────────────────────────────
#
# Django's delete collector removes (CASCADE) or rewrites (SET_NULL, SET_DEFAULT, SET())
# related rows with plain queries — it never calls VersionedModel.delete()/save() or the
# guarded QuerySet. So deleting an object that locked rows point to would silently change a
# locked release. A pre_delete receiver on every model that versioned rows point to closes
# that hole: it runs for each object the collector is about to delete, before anything is
# written, and an exception rolls the whole delete back. Like a DB integrity error, it is raised
# inside the delete's transaction: inside an outer atomic() block, that block must be exited
# (or wrapped in a nested atomic()) before running further queries.

_NO_CASCADE_EFFECT = (models.DO_NOTHING, models.PROTECT, models.RESTRICT)
_cascade_guards: dict[type[models.Model], dict[str, Any]] = {}  # sender -> {dispatch_uid: guard}
_release_being_deleted: ContextVar[int | None] = ContextVar("release_being_deleted", default=None)
_release_being_built: ContextVar[int | None] = ContextVar("release_being_built", default=None)
_raw_load_allowed: ContextVar[bool] = ContextVar("raw_load_allowed", default=False)


@contextmanager
def allow_raw_load() -> Iterator[None]:
    """
    Let fixture loading (loaddata) write rows of locked or deployed releases — for restoring a full dump.
    Used by the restore_releases command, which verifies isolation after the load.
    """
    token = _raw_load_allowed.set(True)
    try:
        yield
    finally:
        _raw_load_allowed.reset(token)


# pylint: disable-next=W0613
def _raw_save_guard(sender: type[models.Model], instance: models.Model, raw: bool, **kwargs: Any) -> None:
    """
    pre_save guard for fixture loading. loaddata saves "raw" — past save() and so past every check there —
    so the same rules run here: no writes to a locked release, no moves, no references across releases,
    and no changes to a deployed release's frozen fields.
    """
    if not raw or _raw_load_allowed.get():
        return
    if isinstance(instance, VersionedModel) and (errors := instance.release_errors(stored_from_db=True)):
        raise ValidationError(errors)
    if (check := getattr(instance, "deployed_change_error", None)) and (message := check()):
        raise ValidationError(message)


@contextmanager
def building_release(release_id: int) -> Iterator[None]:
    """
    Skip the per-row lock check for writes into one release while create_release fills it.

    The new release is created unlocked inside create_release's own transaction, so no other
    connection can see or lock it until the copy commits — checking it for every row is pure overhead.
    """
    token = _release_being_built.set(release_id)
    try:
        yield
    finally:
        _release_being_built.reset(token)


@contextmanager
def allow_release_deletion(release_id: int) -> Iterator[None]:
    """
    Let the cascade guard ignore rows of one release while that release is being deleted.
    Used by services.delete_release() — the one deliberate way to remove locked rows.
    """
    token = _release_being_deleted.set(release_id)
    try:
        yield
    finally:
        _release_being_deleted.reset(token)


def _cascading_fields(model: type[models.Model]) -> Iterator[models.ForeignKey]:
    """Forward FK / one-to-one fields of a versioned model whose on_delete changes this model's rows."""
    for field in model._meta.get_fields():  # pylint: disable=W0212
        if field.many_to_one or field.one_to_one:
            if field.concrete and field.remote_field.on_delete not in _NO_CASCADE_EFFECT:
                yield field


def _frozen_release_q(prefix: str = "") -> Q:
    """Rows whose release (reached through `prefix`, e.g. "part__") is locked or deployed."""
    return Q(**{f"{prefix}release__is_locked": True}) | Q(**{f"{prefix}release__deployed": True})


def _make_cascade_guard(model: type[models.Model], field: models.ForeignKey, release_prefix: str = "") -> Any:
    """
    pre_delete guard for the model `field` points to. `model` holds the affected rows; `release_prefix`
    is the path from those rows to the versioned row that owns them ("" for a versioned model itself,
    "<fk>__" for the through model of a many-to-many field).
    """

    def guard(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:  # pylint: disable=W0613
        target = instance.pk if field.target_field.primary_key else getattr(instance, field.target_field.attname)
        base_manager = model._base_manager  # pylint: disable=W0212
        frozen = base_manager.filter(**{field.attname: target}).filter(_frozen_release_q(release_prefix))
        if (deleting := _release_being_deleted.get()) is not None:
            frozen = frozen.exclude(**{f"{release_prefix}release_id": deleting})
        if locked := sorted(set(frozen.values_list(f"{release_prefix}release__version", flat=True))):
            raise ValidationError(
                f"Cannot delete {sender._meta.label} {instance.pk}: {model._meta.label} rows of locked "  # pylint: disable=W0212
                f"release {', '.join(locked)} point to it ({field.name}, "
                f"on_delete={field.remote_field.on_delete.__name__}). Create a new release (patch) instead."
            )

    return guard


def _plain_m2m_fields(model: type[models.Model]) -> Iterator[models.ManyToManyField]:
    """Many-to-many fields of a versioned model whose through model is not itself versioned."""
    for field in model._meta.local_many_to_many:  # pylint: disable=W0212
        if not issubclass(field.remote_field.through, VersionedModel):
            yield field


def _frozen_versions(model: type[models.Model], pks: Iterable[Any]) -> set[str]:
    if not issubclass(model, VersionedModel) or not (pks := list(pks)):
        return set()
    base_manager = model._base_manager  # pylint: disable=W0212
    return set(base_manager.filter(pk__in=pks).filter(_FROZEN_RELEASE_Q).values_list("release__version", flat=True))


def _make_m2m_guard(field: models.ManyToManyField) -> Any:
    """m2m_changed guard: refuse add / remove / clear / set on links of a locked or deployed row."""
    through = field.remote_field.through
    source_fk, target_fk = field.m2m_field_name(), field.m2m_reverse_field_name()

    # pylint: disable=W0613,R0913
    def guard(
        sender: type[models.Model],
        instance: models.Model,
        action: str,
        reverse: bool,
        model: type[models.Model],
        pk_set: set[Any] | None,
        **kwargs: Any,
    ) -> None:
        if action not in ("pre_add", "pre_remove", "pre_clear") or _raw_load_allowed.get():
            return  # a restore (allow_raw_load) re-creates links of locked rows; isolation is verified after it
        if action == "pre_add" and isinstance(instance, VersionedModel) and issubclass(model, VersionedModel):
            base_manager = model._base_manager  # pylint: disable=W0212
            other = base_manager.filter(pk__in=pk_set).exclude(release_id=instance.release_id)
            if (stray := other.values_list("pk", flat=True).first()) is not None:
                raise ValidationError(_isolation_error(type(instance), field.name, model, stray))
        own_fk, other_fk = (target_fk, source_fk) if reverse else (source_fk, target_fk)
        if pk_set is None:  # clear — every currently linked row is affected
            linked = through._base_manager.filter(**{own_fk: instance.pk})  # pylint: disable=W0212
            pk_set = set(linked.values_list(f"{other_fk}_id", flat=True))
        if locked := sorted(_frozen_versions(type(instance), [instance.pk]) | _frozen_versions(model, pk_set)):
            raise ValidationError(
                f"Cannot {action.removeprefix('pre_')} {field.model.__name__}.{field.name} links: "
                f"release {', '.join(locked)} is locked. Create a new release (patch) instead."
            )

    return guard


def _register_guard(sender: type[models.Model], uid: str, guard: Any) -> Any:
    """Keep this library's guards per sender (keyed like the signal's dispatch_uid) for delete_errors()."""
    _cascade_guards.setdefault(sender, {})[uid] = guard
    return guard


def delete_errors(instance: models.Model) -> list[str]:
    """
    Why deleting `instance` would be refused, without deleting anything: the instance is a row of a locked
    or deployed release, or the delete would cascade into rows (or links) of one. Empty if it can be deleted.
    Only the instance itself is checked against the cascade guards — callers checking a whole cascade
    (e.g. the admin's delete confirmation) pass every collected object.
    """
    messages = []
    if isinstance(instance, VersionedModel) and (locked := _locked_versions([instance.release_id])):
        messages.append(_locked_message(locked, "delete"))
    for guard in _cascade_guards.get(type(instance), {}).values():
        try:
            guard(sender=type(instance), instance=instance)
        except ValidationError as exc:
            messages.extend(exc.messages)
    return messages


def connect_cascade_guards(versioned_models: Iterable[type[models.Model]]) -> None:
    """
    Register the lock guards that Django's own machinery would otherwise bypass. Called from AppConfig.ready().

    - pre_delete on every model a versioned row's FK points to (cascades into locked rows).
    - pre_delete on every model the through table of a versioned many-to-many field points to
      (cascades into the links of locked rows).
    - m2m_changed on every such through table (add / remove / clear / set on locked rows).
    - pre_save on Release and every versioned model, for raw saves (fixture loading).
    """
    from django_versioned_models.models import Release  # pylint: disable=C0415

    pre_save.connect(_raw_save_guard, sender=Release, weak=False, dispatch_uid="versioned_raw_guard:release")
    for model in versioned_models:
        pre_save.connect(
            _raw_save_guard,
            sender=model,
            weak=False,
            dispatch_uid=f"versioned_raw_guard:{model._meta.label}",  # pylint: disable=W0212
        )
        for field in _cascading_fields(model):
            uid = f"versioned_cascade_guard:{model._meta.label}.{field.name}"  # pylint: disable=W0212
            pre_delete.connect(
                _register_guard(field.related_model, uid, _make_cascade_guard(model, field)),
                sender=field.related_model,
                weak=False,
                dispatch_uid=uid,
            )
        for m2m_field in _plain_m2m_fields(model):
            through = m2m_field.remote_field.through
            source_fk = m2m_field.m2m_field_name()
            uid = f"{model._meta.label}.{m2m_field.name}"  # pylint: disable=W0212
            for through_fk in _cascading_fields(through):
                if through_fk.name != source_fk:
                    guard_uid = f"versioned_m2m_cascade_guard:{uid}.{through_fk.name}"
                    pre_delete.connect(
                        _register_guard(
                            through_fk.related_model,
                            guard_uid,
                            _make_cascade_guard(through, through_fk, release_prefix=f"{source_fk}__"),
                        ),
                        sender=through_fk.related_model,
                        weak=False,
                        dispatch_uid=guard_uid,
                    )
            m2m_changed.connect(
                _make_m2m_guard(m2m_field), sender=through, weak=False, dispatch_uid=f"versioned_m2m_guard:{uid}"
            )
