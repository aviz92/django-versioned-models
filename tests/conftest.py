import pytest

from django_versioned_models.mixins import DataStatus
from django_versioned_models.models import Release
from tests.testapp.models import Category, Product


@pytest.fixture
def release(db: None) -> Release:  # pylint: disable=W0621
    return Release.objects.create(version="v1.0.0", description="Initial release")


@pytest.fixture
def locked_release(db: None) -> Release:  # pylint: disable=W0621
    r = Release.objects.create(version="v1.0.0-locked")
    r.lock()
    return r


@pytest.fixture
def category(release: Release) -> Category:  # pylint: disable=W0621
    return Category.objects.create(name="Electronics", release=release)


@pytest.fixture
def approved_category(release: Release) -> Category:  # pylint: disable=W0621
    cat = Category.objects.create(name="Approved Cat", release=release)
    cat.approve()
    return cat


@pytest.fixture
def product(release: Release, category: Category) -> Product:  # pylint: disable=W0621
    return Product.objects.create(name="Laptop", release=release, category=category)


@pytest.fixture
def locked_release_with_data(db: None) -> Release:  # pylint: disable=W0621
    """A locked release that has approved Category and Product rows."""
    r = Release.objects.create(version="v2.0.0")
    cat = Category.objects.create(name="Electronics", release=r)
    cat.approve()
    Product.objects.create(name="Laptop", release=r, category=cat)
    p2 = Product.objects.create(name="Phone", release=r, category=cat)
    p2.approve()
    inactive = Category.objects.create(name="Inactive Cat", release=r)
    inactive.deactivate()
    r.lock()
    return r
