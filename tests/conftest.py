import pytest

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from tests.testapp.models import Category, Product


@pytest.fixture
def release(db) -> Release:
    return Release.objects.create(version="v1.0.0", description="Initial release")


@pytest.fixture
def locked_release(db) -> Release:
    r = Release.objects.create(version="v1.0.0-locked")
    r.lock()
    return r


@pytest.fixture
def category(release: Release) -> Category:
    return Category.objects.create(name="Electronics", release=release)


@pytest.fixture
def approved_category(release: Release) -> Category:
    cat = Category.objects.create(name="Approved Cat", release=release)
    cat.approve()
    return cat


@pytest.fixture
def product(release: Release, category: Category) -> Product:
    return Product.objects.create(name="Laptop", release=release, category=category)


@pytest.fixture
def locked_release_with_data(db) -> Release:
    """A locked release that has approved Category and Product rows."""
    r = Release.objects.create(version="v2.0.0")
    cat = Category.objects.create(name="Electronics", release=r)
    cat.approve()
    Product.objects.create(name="Laptop", release=r, category=cat)
    p2 = Product.objects.create(name="Phone", release=r, category=cat)
    p2.approve()
    # Also create an inactive row to verify it is copied
    inactive = Category.objects.create(name="Inactive Cat", release=r)
    inactive.deactivate()
    r.lock()
    return r
