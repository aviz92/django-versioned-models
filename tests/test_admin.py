# pylint: disable=W0212  # legacy data is written past the guards with _base_manager
import pytest
from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.test import Client
from django.urls import reverse

from django_versioned_models.admin import VersionedModelForm
from django_versioned_models.models import Release
from tests.testapp.models import Category, Part, Product, Supplier, Tag


def _url(model: type, action: str, *args: object) -> str:
    return reverse(f"admin:testapp_{model._meta.model_name}_{action}", args=args)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "release", "category", "status", "active"]


class ProductNameOnlyForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name"]


class PartForm(VersionedModelForm):
    class Meta:
        model = Part
        fields = ["name", "release", "tags", "status", "active"]


@pytest.mark.django_db
class TestModelValidation:
    def test_full_clean_reports_cross_release_fk_on_the_field(self, release: Release, other_release: Release) -> None:
        product = Product(name="P", release=release, category=Category.objects.create(name="C", release=other_release))
        with pytest.raises(ValidationError) as exc:
            product.full_clean()
        assert "category" in exc.value.message_dict, "The error must be attached to the offending field"

    def test_form_cross_release_fk_is_a_field_error(self, release: Release, other_release: Release) -> None:
        category = Category.objects.create(name="C", release=other_release)
        form = ProductForm(
            data={"name": "P", "release": release.pk, "category": category.pk, "status": "draft", "active": True}
        )
        assert not form.is_valid(), "A cross-release FK must not validate"
        assert "must point to a row in the same release" in form.errors["category"][0], "Error shown on the field"
        assert not Product.objects.exists(), "Nothing must be saved"

    def test_form_error_for_field_not_on_the_form_goes_to_non_field_errors(
        self, release: Release, other_release: Release
    ) -> None:
        product = Product.objects.create(name="P", release=release)
        Product._base_manager.filter(pk=product.pk).update(
            category=Category.objects.create(name="C", release=other_release)
        )
        product.refresh_from_db()
        form = ProductNameOnlyForm(data={"name": "Renamed"}, instance=product)
        assert not form.is_valid(), "A legacy cross-release FK must still be reported"
        assert NON_FIELD_ERRORS in form.errors, "An error for a field the form doesn't show must not crash the form"

    def test_form_on_locked_row_is_a_non_field_error(self, release: Release, category: Category) -> None:
        release.lock()
        form = ProductForm(
            data={"name": "P", "release": release.pk, "category": category.pk, "status": "draft", "active": True}
        )
        assert not form.is_valid(), "A row in a locked release must not validate"
        assert "is locked" in form.errors["release"][0], "Choosing a locked release is reported on the release field"

    def test_form_editing_row_of_locked_release_is_rejected(self, release: Release) -> None:
        product = Product.objects.create(name="P", release=release)
        release.lock()
        form = ProductNameOnlyForm(data={"name": "Renamed"}, instance=product)
        assert not form.is_valid(), "Editing a locked row must not validate"
        assert "is locked" in form.errors[NON_FIELD_ERRORS][0], "Reported as a form-wide error"

    def test_form_moving_row_to_other_release_is_rejected(self, release: Release, other_release: Release) -> None:
        product = Product.objects.create(name="P", release=release)
        form = ProductForm(
            data={"name": "P", "release": other_release.pk, "status": "draft", "active": True}, instance=product
        )
        assert not form.is_valid(), "Moving a row must not validate"
        assert "cannot move between releases" in form.errors["release"][0], "Reported on the release field"

    def test_valid_form_saves(self, release: Release, category: Category) -> None:
        form = ProductForm(
            data={"name": "P", "release": release.pk, "category": category.pk, "status": "draft", "active": True}
        )
        assert form.is_valid(), form.errors
        assert form.save().category_id == category.pk, "A same-release FK must save"

    def test_versioned_form_cross_release_m2m_is_a_field_error(self, release: Release, other_release: Release) -> None:
        tag = Tag.objects.create(name="T", release=other_release)
        form = PartForm(data={"name": "A", "release": release.pk, "tags": [tag.pk], "status": "draft", "active": True})
        assert not form.is_valid(), "A cross-release m2m selection must not validate"
        assert "Part.tags" in form.errors["tags"][0], "Error shown on the m2m field"
        assert not Part.objects.exists(), "Nothing must be saved"


@pytest.mark.django_db
class TestVersionedModelAdmin:
    def test_change_cross_release_fk_shows_form_error(
        self, admin_client: Client, release: Release, other_release: Release
    ) -> None:
        part = Part.objects.create(name="A", release=release)
        foreign = Part.objects.create(name="B", release=other_release)
        response = admin_client.post(
            _url(Part, "change", part.pk),
            {"name": "A", "release": release.pk, "parent": foreign.pk, "status": "draft", "active": "on"},
        )
        assert response.status_code == 200, "The change form must come back with an error, not crash"
        assert Part.objects.get(pk=part.pk).parent_id is None, "Nothing must be saved"

    def test_add_cross_release_m2m_shows_form_error(
        self, admin_client: Client, release: Release, other_release: Release
    ) -> None:
        tag = Tag.objects.create(name="T", release=other_release)
        response = admin_client.post(
            _url(Part, "add"), {"name": "A", "release": release.pk, "tags": [tag.pk], "status": "draft", "active": "on"}
        )
        assert response.status_code == 200, "The add form must come back with an error, not crash"
        assert "must point to a row in the same release" in response.content.decode(), "The error must be shown"
        assert not Part.objects.exists(), "Nothing must be created"

    def test_add_valid_row_succeeds(self, admin_client: Client, release: Release) -> None:
        tag = Tag.objects.create(name="T", release=release)
        response = admin_client.post(
            _url(Part, "add"), {"name": "A", "release": release.pk, "tags": [tag.pk], "status": "draft", "active": "on"}
        )
        assert response.status_code == 302, "A valid row must be saved"
        assert list(Part.objects.get(name="A").tags.all()) == [tag], "The same-release link must be saved"

    def test_choices_are_limited_to_the_rows_release(
        self, admin_client: Client, release: Release, other_release: Release
    ) -> None:
        part = Part.objects.create(name="A", release=release)
        Part.objects.create(name="B", release=other_release)
        Tag.objects.create(name="T-other", release=other_release)
        own_tag = Tag.objects.create(name="T-own", release=release)
        form = admin_client.get(_url(Part, "change", part.pk)).context["adminform"].form
        assert set(form.fields["parent"].queryset) == {part}, "FK choices must only list the row's release"
        assert list(form.fields["tags"].queryset) == [own_tag], "m2m choices must only list the row's release"

    def test_locked_row_is_read_only(self, admin_client: Client, release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        release.lock()
        assert admin_client.get(_url(Part, "change", part.pk)).status_code == 200, "Locked rows stay viewable"
        response = admin_client.post(
            _url(Part, "change", part.pk), {"name": "Hacked", "release": release.pk, "status": "draft", "active": "on"}
        )
        assert response.status_code == 403, "Saving a locked row must be refused, not crash"
        assert Part.objects.get(pk=part.pk).name == "A", "The locked row must stay unchanged"

    def test_delete_locked_row_is_refused(self, admin_client: Client, release: Release) -> None:
        part = Part.objects.create(name="A", release=release)
        release.lock()
        assert admin_client.post(_url(Part, "delete", part.pk), {"post": "yes"}).status_code == 403, "Must be refused"
        assert Part.objects.filter(pk=part.pk).exists(), "The locked row must survive"

    def test_delete_object_cascading_into_locked_rows_is_blocked(
        self, admin_client: Client, release: Release, supplier: Supplier
    ) -> None:
        Part.objects.create(name="A", release=release, supplier=supplier)
        release.lock()
        response = admin_client.post(_url(Supplier, "delete", supplier.pk), {"post": "yes"})
        assert response.status_code == 200, "The confirmation page must explain the refusal, not crash"
        assert "locked release" in response.content.decode(), "The reason must be shown"
        assert Supplier.objects.filter(pk=supplier.pk).exists(), "Nothing must be deleted"

    def test_bulk_delete_with_locked_rows_is_blocked(
        self, admin_client: Client, release: Release, other_release: Release
    ) -> None:
        free = Part.objects.create(name="Free", release=other_release)
        frozen = Part.objects.create(name="Frozen", release=release)
        release.lock()
        response = admin_client.post(
            _url(Part, "changelist"),
            {"action": "delete_selected", "_selected_action": [free.pk, frozen.pk], "post": "yes"},
        )
        assert response.status_code == 200, "The action must explain the refusal, not crash"
        assert "is locked" in response.content.decode(), "The reason must be shown"
        assert Part.objects.count() == 2, "Nothing must be deleted"

    def test_bulk_delete_of_unlocked_rows_succeeds(self, admin_client: Client, release: Release) -> None:
        parts = [Part.objects.create(name=n, release=release) for n in ("A", "B")]
        response = admin_client.post(
            _url(Part, "changelist"),
            {"action": "delete_selected", "_selected_action": [p.pk for p in parts], "post": "yes"},
        )
        assert response.status_code == 302, "Unlocked rows must still be deletable"
        assert not Part.objects.exists(), "Both rows must be deleted"
