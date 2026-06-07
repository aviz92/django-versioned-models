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
