import pytest

from django_versioned_models.models import Release
from django_versioned_models.services import create_release, get_versioned_models_ordered
from tests.testapp.models import Category, Part, PartSpec, Product, Step


def _branch(release: Release) -> Release:
    release.lock()
    return create_release("v2.0.0", release.version)


@pytest.mark.django_db
class TestSelfReferenceCopy:
    def test_child_copied_before_parent_points_to_new_parent(self, release: Release) -> None:
        child = Part.objects.create(name="Child", release=release)
        parent = Part.objects.create(name="Parent", release=release)
        child.parent = parent
        child.save()
        new = _branch(release)
        copy = Part.objects.get(release=new, name="Child")
        assert copy.parent.release_id == new.pk, "Child copy must point to the parent copy in the new release"
        assert copy.parent.name == "Parent", "Child copy must point to the copy of its own parent"

    def test_mutual_references_are_remapped(self, release: Release) -> None:
        a = Part.objects.create(name="A", release=release)
        b = Part.objects.create(name="B", release=release, parent=a)
        a.parent = b
        a.save()
        new = _branch(release)
        a2, b2 = Part.objects.get(release=new, name="A"), Part.objects.get(release=new, name="B")
        assert (a2.parent_id, b2.parent_id) == (b2.pk, a2.pk), "A cycle must be remapped inside the new release"

    def test_row_pointing_to_itself_is_remapped(self, release: Release) -> None:
        part = Part.objects.create(name="Loop", release=release)
        part.parent = part
        part.save()
        new = _branch(release)
        copy = Part.objects.get(release=new)
        assert copy.parent_id == copy.pk, "A self-pointing row must point to its own copy"

    def test_source_rows_are_untouched(self, release: Release) -> None:
        child = Part.objects.create(name="Child", release=release)
        parent = Part.objects.create(name="Parent", release=release)
        child.parent = parent
        child.save()
        _branch(release)
        assert Part.objects.get(pk=child.pk).parent_id == parent.pk, "Source child must keep its parent"

    def test_self_reference_outside_source_release_raises(self, release: Release) -> None:
        other = Release.objects.create(version="v-other")
        Part.objects.create(name="Child", release=release, parent=Part.objects.create(name="X", release=other))
        release.lock()
        with pytest.raises(ValueError, match="not in the source release"):
            create_release("v2.0.0", release.version)
        assert not Release.objects.filter(version="v2.0.0").exists(), "Failed branch must roll back completely"

    def test_non_nullable_self_reference_raises(self, release: Release) -> None:
        Step.objects.create(pk=1, name="First", previous_id=1, release=release)
        release.lock()
        with pytest.raises(ValueError, match="previous must be nullable"):
            create_release("v2.0.0", release.version)
        assert not Release.objects.filter(version="v2.0.0").exists(), "Failed branch must roll back completely"


@pytest.mark.django_db
class TestForeignKeyCopy:
    def test_fk_to_versioned_row_outside_source_release_raises(self, release: Release) -> None:
        other = Release.objects.create(version="v-other")
        Product.objects.create(
            name="Laptop", release=release, category=Category.objects.create(name="X", release=other)
        )
        release.lock()
        with pytest.raises(ValueError, match="category points to Category"):
            create_release("v2.0.0", release.version)
        assert not Release.objects.filter(version="v2.0.0").exists(), "Failed branch must roll back completely"

    def test_one_to_one_is_remapped(self, release: Release) -> None:
        PartSpec.objects.create(part=Part.objects.create(name="Bolt", release=release), weight=7, release=release)
        new = _branch(release)
        spec = PartSpec.objects.get(release=new)
        assert spec.part.release_id == new.pk, "One-to-one must point to the copy in the new release"
        assert spec.weight == 7, "Other fields must be copied"

    def test_one_to_one_target_is_ordered_first(self) -> None:
        ordered = get_versioned_models_ordered()
        assert ordered.index(Part) < ordered.index(PartSpec), "One-to-one target must be copied first"
