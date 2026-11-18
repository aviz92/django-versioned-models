from django.contrib import admin

from django_versioned_models.admin import VersionedModelAdmin
from tests.testapp.models import Category, Part, Product, Supplier, Tag

for model in (Category, Part, Product, Tag, Supplier):
    admin.site.register(model, VersionedModelAdmin)
