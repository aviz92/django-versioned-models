"""
Admin and form support — the release rules as form errors instead of server errors.

Usage:
    from django.contrib import admin
    from django_versioned_models.admin import VersionedModelAdmin

    @admin.register(Product)
    class ProductAdmin(VersionedModelAdmin):
        ...

What VersionedModelAdmin adds on top of ModelAdmin:
    - Rows of a locked or deployed release are read-only: no save, no delete.
    - FK and many-to-many choices only list rows of the edited row's release.
    - Many-to-many selections are validated against the row's release (VersionedModelForm).
    - A delete that would cascade into rows (or links) of a locked release is refused on the
      confirmation page — for the delete view and the "delete selected" action alike.
FK / one-to-one isolation, locks and moves are validated by VersionedModel.clean() in any ModelForm.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.utils import NestedObjects
from django.db import router
from django.db.models import Model
from django.http import HttpRequest

from django_versioned_models.mixins import VersionedModel, _isolation_error, _locked_versions, delete_errors

_ADMIN_OBJ_ATTR = "_versioned_admin_obj"  # the object being edited, stashed on the request by get_form()


class VersionedModelForm(forms.ModelForm):
    """ModelForm that also checks many-to-many selections against the row's release."""

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        release = cleaned.get("release") if "release" in self.fields else None
        if (release_id := getattr(release, "pk", None) or getattr(self.instance, "release_id", None)) is None:
            return cleaned
        for field in self.instance._meta.many_to_many:  # pylint: disable=W0212
            if field.name not in cleaned or not issubclass(field.related_model, VersionedModel):
                continue
            if stray := next((obj for obj in cleaned[field.name] or () if obj.release_id != release_id), None):
                self.add_error(
                    field.name, _isolation_error(type(self.instance), field.name, field.related_model, stray.pk)
                )
        return cleaned


class VersionedModelAdmin(admin.ModelAdmin):
    """ModelAdmin for versioned models — see the module docstring."""

    form = VersionedModelForm

    # ── Locked rows are read-only ─────────────────────────────────────────────

    @staticmethod
    def _is_frozen(obj: Model | None) -> bool:
        return isinstance(obj, VersionedModel) and bool(_locked_versions([obj.release_id]))

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return not self._is_frozen(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return not self._is_frozen(obj) and super().has_delete_permission(request, obj)

    # ── Choices limited to the row's release ──────────────────────────────────

    def get_form(self, request: HttpRequest, obj: Model | None = None, change: bool = False, **kwargs: Any) -> Any:
        setattr(request, _ADMIN_OBJ_ATTR, obj)  # read by formfield_for_* below
        return super().get_form(request, obj, change=change, **kwargs)

    def _limit_to_release(self, db_field: Any, request: HttpRequest, kwargs: dict[str, Any]) -> None:
        obj = getattr(request, _ADMIN_OBJ_ATTR, None)
        if db_field.name == "release" or not isinstance(obj, VersionedModel) or obj.release_id is None:
            return
        if issubclass(db_field.related_model, VersionedModel) and "queryset" not in kwargs:
            manager = db_field.related_model._default_manager  # pylint: disable=W0212
            kwargs["queryset"] = manager.filter(release_id=obj.release_id)

    def formfield_for_foreignkey(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        self._limit_to_release(db_field, request, kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        self._limit_to_release(db_field, request, kwargs)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    # ── Deletes that would touch locked rows ──────────────────────────────────

    def get_deleted_objects(self, objs: Sequence[Model] | Iterable[Model], request: HttpRequest) -> tuple[Any, ...]:
        objs = list(objs)
        to_delete, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        collector = NestedObjects(using=router.db_for_write(self.model))
        collector.collect(objs)
        blocked: list[str] = []
        for instances in collector.data.values():
            for instance in instances:
                blocked.extend(m for m in delete_errors(instance) if m not in blocked)
        if not blocked:
            return to_delete, model_count, perms_needed, protected
        # The admin refuses to delete while "protected" is non-empty and lists its entries on the
        # confirmation page — the same way it handles PROTECT foreign keys. Locked rows also report no
        # delete permission, and the admin would show that ("no permission to delete …") instead of the
        # real reason, so the permission list is dropped while the delete is blocked anyway.
        return to_delete, model_count, set(), list(protected) + blocked
