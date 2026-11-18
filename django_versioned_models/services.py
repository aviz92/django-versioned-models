"""
Core services — create_release, lock_release, rename_release, delete_release, and auto-discovery.
"""

from typing import Any

from django.apps import apps
from django.db import transaction
from django.db.models import ManyToManyField, Model, ProtectedError, RestrictedError

from django_versioned_models.mixins import VersionedModel, allow_release_deletion
from django_versioned_models.models import Release


def get_versioned_models() -> list[type[Model]]:
    """
    Auto-discover all models that inherit from VersionedModel.
    No manual registration needed — just inherit and you're in.
    """
    return [model for model in apps.get_models() if issubclass(model, VersionedModel) and model is not VersionedModel]


def get_versioned_models_ordered() -> list[type[VersionedModel]]:
    """
    Returns versioned models sorted by FK dependencies (parents before children).
    Uses Kahn's topological sort algorithm.
    """
    models = get_versioned_models()
    model_set = set(models)

    graph = {m: set() for m in models}
    for model in models:
        for field in model._meta.get_fields():  # pylint: disable=W0212
            if not field.is_relation or not (field.many_to_one or field.one_to_one) or not field.concrete:
                continue
            related = field.related_model
            if related in model_set and related is not model:
                graph[model].add(related)

    ordered: list[type[VersionedModel]] = []
    ordered_set: set[type[VersionedModel]] = set()
    no_deps = [m for m, deps in graph.items() if not deps]

    while no_deps:  # pylint: disable=W0149
        m = no_deps.pop()
        ordered.append(m)
        ordered_set.add(m)
        for other, deps in graph.items():
            if m in deps:
                deps.discard(m)
                if not deps and other not in ordered_set:
                    no_deps.append(other)

    if len(ordered) != len(models):
        remaining = [m.__name__ for m in models if m not in ordered]
        raise RuntimeError(f"Circular FK dependency detected among versioned models: {remaining}")

    return ordered


@transaction.atomic
def create_release(version: str, based_on_version: str, description: str = "", user_id: int | None = None) -> Release:
    """
    Create a new release branched from an existing locked one.
    Copies all versioned rows automatically, including inactive ones —
    so architects can reactivate them in the new release if needed.
    """
    try:
        source_release = Release.objects.get(version=based_on_version)
    except Release.DoesNotExist as exc:
        raise ValueError(f'Source release "{based_on_version}" does not exist.') from exc

    if not source_release.is_locked:
        raise ValueError(
            f'Source release "{based_on_version}" is not locked yet. ' f"You can only branch from a locked release."
        )

    new_release = Release.objects.create(
        version=version,
        description=description,
        based_on=source_release,
        is_locked=False,
        created_by_id=user_id,
    )

    id_mapping = {}
    ordered = get_versioned_models_ordered()
    for model in ordered:
        _copy_model_rows(model, source_release, new_release, id_mapping)
    # Links last — every versioned row on both ends of a link must already have its copy.
    for model in ordered:
        _copy_m2m_links(model, source_release, id_mapping)

    return new_release


def _model_key(model: type[Model]) -> str:
    return f"{model._meta.app_label}.{model.__name__}"  # pylint: disable=W0212


def _copy_m2m_links(model: type[VersionedModel], source_release: Release, id_mapping: dict) -> None:
    """
    Copy the many-to-many links of a model's rows from source_release to the new release.

    Each link row is duplicated with both ends remapped: a versioned end points to its copy in the
    new release, a non-versioned end stays as-is. Extra fields of a custom through model are kept.
    A versioned through model is skipped — its rows were already copied like any versioned model.

    Raises:
        ValueError: if a link points to a versioned row outside the source release (it has no copy).
    """
    for field in model._meta.local_many_to_many:  # pylint: disable=W0212
        through = field.remote_field.through
        if issubclass(through, VersionedModel):
            continue
        source_fk = field.m2m_field_name()
        links = through._base_manager.filter(**{f"{source_fk}__release": source_release})  # pylint: disable=W0212
        new_links = [through(**_remapped_values(through, link, id_mapping, field)) for link in links]
        through._base_manager.bulk_create(new_links)  # pylint: disable=W0212


def _remapped_values(through: type[Model], link: Model, id_mapping: dict, field: ManyToManyField) -> dict[str, Any]:
    values = {}
    for through_field in through._meta.concrete_fields:  # pylint: disable=W0212
        if through_field.primary_key:
            continue
        value = getattr(link, through_field.attname)
        if through_field.is_relation and value is not None:
            if (mapping := id_mapping.get(_model_key(through_field.related_model))) is not None:
                if (new_row := mapping.get(value)) is None:
                    raise ValueError(
                        f"Cannot copy {field.model.__name__}.{field.name}: it links to "
                        f"{through_field.related_model.__name__} {value}, which is not in the source release."
                    )
                value = new_row.pk
        values[through_field.attname] = value
    return values


def _copy_model_rows(
    model: type[VersionedModel], source_release: Release, new_release: Release, id_mapping: dict
) -> None:
    """
    Copy all rows of a model from source_release to new_release, remapping FKs.
    Uses all_rows() to include inactive rows — architects can reactivate them
    in the new release if needed. Active state is preserved as-is.

    FK and one-to-one fields to versioned models point to the copies in the new release; fields to
    non-versioned models keep their value. A self-reference (a row pointing to another row of the same
    model) is set in a second pass, once every row of the model has its copy — so the copy order of
    the rows doesn't matter.

    Raises:
        ValueError: if a row points to a versioned row outside the source release (it has no copy),
            or the model has a non-nullable self-reference (it can't be set in a second pass).
    """
    source_rows = list(model.objects.all_rows(source_release).order_by("pk"))
    mapping = id_mapping[_model_key(model)] = {}
    self_fks = [f for f in _forward_fks(model) if f.related_model is model]
    if source_rows and (required := [f.name for f in self_fks if not f.null]):
        raise ValueError(
            f"Cannot copy {model.__name__}: self-reference {', '.join(required)} must be nullable "
            f"so it can be set after all rows are copied."
        )

    deferred: list[tuple[Model, Any, Any]] = []  # (new row, self-FK field, old target pk)
    for row in source_rows:
        field_values = {}
        row_deferred = []
        for field in model._meta.concrete_fields:  # pylint: disable=W0212
            if field.primary_key or field.name == "release":
                continue
            value = getattr(row, field.attname)
            if value is not None and field in self_fks:
                row_deferred.append((field, value))
                value = None
            elif value is not None and field.is_relation:
                value = _remap(model, row, field, value, id_mapping)
            field_values[field.attname] = value  # attname: an FK to a non-versioned model keeps its id

        new_row = model.objects.create(**field_values, release=new_release)
        mapping[row.pk] = new_row
        deferred.extend((new_row, field, value) for field, value in row_deferred)

    _apply_self_references(model, mapping, deferred)


def _apply_self_references(model: type[Model], mapping: dict, deferred: list[tuple[Model, Any, Any]]) -> None:
    """Second pass: point each deferred self-reference at the copy of its target."""
    if not deferred:
        return
    for new_row, field, old_target in deferred:
        if (target := mapping.get(old_target)) is None:
            raise ValueError(
                f"Cannot copy {model.__name__}.{field.name}: it points to {model.__name__} {old_target}, "
                f"which is not in the source release."
            )
        setattr(new_row, field.attname, target.pk)
    model.objects.bulk_update({row for row, _, _ in deferred}, sorted({f.attname for _, f, _ in deferred}))


def _forward_fks(model: type[Model]) -> list[Any]:
    """Concrete FK and one-to-one fields of a model, excluding the release FK."""
    return [
        f
        for f in model._meta.concrete_fields  # pylint: disable=W0212
        if f.is_relation and (f.many_to_one or f.one_to_one) and f.name != "release"
    ]


def _remap(model: type[Model], row: Model, field: Any, value: Any, id_mapping: dict) -> Any:
    """Map an FK value to the copy of its target in the new release; non-versioned targets keep it."""
    if (mapping := id_mapping.get(_model_key(field.related_model))) is None:
        return value
    if (new_target := mapping.get(value)) is None:
        raise ValueError(
            f"Cannot copy {model.__name__} {row.pk}: {field.name} points to "
            f"{field.related_model.__name__} {value}, which is not in the source release."
        )
    return new_target.pk


@transaction.atomic
def lock_release(version: str) -> Release:
    """Lock a release — immutable after this."""
    try:
        release = Release.objects.get(version=version)
    except Release.DoesNotExist as exc:
        raise ValueError(f'Release "{version}" does not exist.') from exc

    if release.is_locked:
        raise ValueError(f'Release "{version}" is already locked.')

    release.lock()
    return release


def rename_release(version: str, new_version: str) -> Release:
    """
    Rename a release by changing its version string.

    Versioned rows reference the release by primary key, so no data is touched.
    Deployed releases cannot be renamed — external systems may already refer to them by name.

    Raises:
        ValueError: if the new name is empty, too long or taken, the release does not exist, or it is deployed.
    """
    if not (new_version := new_version.strip()):
        raise ValueError("New release version must not be empty.")
    if len(new_version) > (max_length := Release._meta.get_field("version").max_length):  # pylint: disable=W0212
        raise ValueError(f"New release version must be at most {max_length} characters.")
    if new_version == version:
        raise ValueError(f'Release is already named "{version}".')

    try:
        release = Release.objects.get(version=version)
    except Release.DoesNotExist as exc:
        raise ValueError(f'Release "{version}" does not exist.') from exc

    if release.deployed:
        raise ValueError(f'Release "{version}" has been deployed and cannot be renamed.')
    if Release.objects.filter(version=new_version).exists():
        raise ValueError(f'Release "{new_version}" already exists.')

    release.version = new_version
    release.save(update_fields=["version"])
    return release


def _get_deletable_release(version: str, for_update: bool = False) -> Release:
    """Fetch a release and make sure it may be deleted: it exists and is not deployed."""
    queryset = Release.objects.select_for_update() if for_update else Release.objects.all()
    try:
        release = queryset.get(version=version)
    except Release.DoesNotExist as exc:
        raise ValueError(f'Release "{version}" does not exist.') from exc

    if release.deployed:
        raise ValueError(f'Release "{version}" has been deployed and cannot be deleted.')
    return release


def get_child_release_versions(version: str) -> list[str]:
    """Versions of the releases branched directly from the given release (their based_on points at it)."""
    return sorted(Release.objects.filter(based_on__version=version).values_list("version", flat=True))


def count_release_rows(release: Release) -> dict[str, int]:
    """
    Number of versioned rows (active and inactive) stored under a release, per model label.
    Models with no rows in the release are omitted.
    """
    counts = {}
    for model in get_versioned_models_ordered():
        # pylint: disable=W0212
        if count := model._base_manager.filter(release=release).count():
            counts[model._meta.label] = count
    return counts


def delete_release(version: str, dry_run: bool = False) -> dict[str, int]:
    """
    Delete a release together with every versioned row that belongs to it.

    Allowed for draft and locked releases; refused for deployed releases. Releases branched from
    this one are kept, but their based_on is cleared (SET_NULL). Rows are deleted children-first (reverse FK order)
    so PROTECT relations between versioned models in the same release don't block the delete.
    The row-level lock guards are bypassed on purpose — removing a non-deployed release, locked
    or not, is the point of this operation.

    Args:
        version: Version string of the release to delete.
        dry_run: Validate and report what would be deleted, without deleting anything.

    Returns:
        Deleted (or, with dry_run, to-be-deleted) object counts per model label, including the
        release itself. A real delete also counts non-versioned objects removed by CASCADE.

    Raises:
        ValueError: if the release does not exist, is deployed, or other data PROTECTs / RESTRICTs its rows.
    """
    if dry_run:
        release = _get_deletable_release(version)
        return {**count_release_rows(release), Release._meta.label: 1}  # pylint: disable=W0212
    return _delete_release(version)


@transaction.atomic
def _delete_release(version: str) -> dict[str, int]:
    release = _get_deletable_release(version, for_update=True)
    deleted: dict[str, int] = {}
    try:
        with allow_release_deletion(release.pk):
            for model in reversed(get_versioned_models_ordered()):
                # _base_manager is a plain Manager — skips VersionedQuerySet's lock guard.
                _, per_model = model._base_manager.filter(release=release).delete()  # pylint: disable=W0212
                _merge_counts(deleted, per_model)
            _, per_model = release.delete()
            _merge_counts(deleted, per_model)
    except (ProtectedError, RestrictedError) as exc:
        blockers = sorted({obj._meta.label for obj in exc.args[1]})  # pylint: disable=W0212
        raise ValueError(
            f'Release "{version}" cannot be deleted: its rows are still referenced by {", ".join(blockers)}.'
        ) from exc
    return {label: count for label, count in deleted.items() if count}


def _merge_counts(total: dict[str, int], counts: dict[str, int]) -> None:
    for label, count in counts.items():
        total[label] = total.get(label, 0) + count
