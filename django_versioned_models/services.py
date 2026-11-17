"""
Core services — create_release, lock_release, rename_release, delete_release, and auto-discovery.
"""

from django.apps import apps
from django.db import transaction
from django.db.models import Model, ProtectedError, RestrictedError

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
            if not field.is_relation or not field.many_to_one:
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
    for model in get_versioned_models_ordered():
        _copy_model_rows(model, source_release, new_release, id_mapping)

    return new_release


def _copy_model_rows(
    model: type[VersionedModel], source_release: Release, new_release: Release, id_mapping: dict
) -> None:
    """
    Copy all rows of a model from source_release to new_release, remapping FKs.
    Uses all_rows() to include inactive rows — architects can reactivate them
    in the new release if needed. Active state is preserved as-is.
    """
    source_rows = model.objects.all_rows(source_release).select_related("release")
    model_key = f"{model._meta.app_label}.{model.__name__}"  # pylint: disable=W0212
    id_mapping[model_key] = {}

    for row in source_rows:
        old_id = row.pk
        field_values = {}

        for field in model._meta.get_fields():  # pylint: disable=W0212
            if not hasattr(field, "column"):
                continue
            if field.primary_key:
                continue
            if field.name == "release":
                continue

            if field.is_relation and field.many_to_one:
                related_model = field.related_model
                # pylint: disable = W0212
                if (related_key := f"{related_model._meta.app_label}.{related_model.__name__}") in id_mapping:
                    if (old_fk_id := getattr(row, f"{field.name}_id")) is not None:
                        new_related = id_mapping[related_key].get(old_fk_id)
                        field_values[f"{field.name}_id"] = new_related.pk if new_related else old_fk_id
                    else:
                        field_values[f"{field.name}_id"] = None
                    continue

            field_values[field.name] = getattr(row, field.attname)

        new_row = model.objects.create(**field_values, release=new_release)
        id_mapping[model_key][old_id] = new_row


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
