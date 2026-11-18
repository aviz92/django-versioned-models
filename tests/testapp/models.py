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


class Tag(VersionedModel):
    name = models.CharField(max_length=100)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class Part(VersionedModel):
    name = models.CharField(max_length=100)
    tags = models.ManyToManyField(Tag, blank=True, related_name="parts")
    certified_by = models.ManyToManyField(Supplier, blank=True, through="Certification", related_name="certified_parts")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.CASCADE)
    backup_supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="backup_parts"
    )
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class Certification(models.Model):
    """Non-versioned custom through model with an extra field."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    level = models.CharField(max_length=20)

    class Meta:
        app_label = "testapp"


class Kit(VersionedModel):
    name = models.CharField(max_length=100)
    parts = models.ManyToManyField(Part, through="KitPart", related_name="kits")

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class KitPart(VersionedModel):
    """Versioned custom through model — copied as a regular versioned model."""

    kit = models.ForeignKey(Kit, on_delete=models.CASCADE)
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class PartSpec(VersionedModel):
    """One-to-one link between versioned models."""

    part = models.OneToOneField(Part, on_delete=models.CASCADE, related_name="spec")
    weight = models.PositiveIntegerField(default=0)

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class Step(VersionedModel):
    """Non-nullable self-reference — not supported when branching."""

    name = models.CharField(max_length=100)
    previous = models.ForeignKey("self", on_delete=models.PROTECT, related_name="next_steps")

    class Meta(VersionedModel.Meta):
        app_label = "testapp"


class CategoryProxy(Category):
    """Proxy of a versioned model — shares Category's table and must not be copied separately."""

    class Meta:
        proxy = True
        app_label = "testapp"
