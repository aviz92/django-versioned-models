from django.db import models

from django_versioned_models.mixins import VersionedModel


class Category(VersionedModel):
    name = models.CharField(max_length=100)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class Product(VersionedModel):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class CategoryNote(models.Model):
    """Non-versioned model that PROTECTs a versioned row — used to test blocked release deletion."""

    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    text = models.CharField(max_length=100)

    class Meta:
        app_label = "testapp"


class Supplier(models.Model):
    """Non-versioned model that versioned Part rows point to — used to test the cascade guard."""

    name = models.CharField(max_length=100)

    class Meta:
        app_label = "testapp"


class Part(VersionedModel):
    name = models.CharField(max_length=100)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.CASCADE)
    backup_supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="backup_parts"
    )
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"
