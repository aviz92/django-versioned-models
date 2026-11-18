import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from django_versioned_models.models import Release
from django_versioned_models.services import create_release, delete_release
from tests.testapp.models import Certification, Kit, KitPart, Part, Supplier, Tag


@pytest.mark.django_db
class TestCreateReleaseCopiesManyToMany:
    def test_create_release_remaps_links_to_new_release(self, release: Release, tagged_part: Part) -> None:
        release.lock()
        new = create_release("v2.0.0", release.version)
        copy = Part.objects.get(release=new, name="Bolt")
        assert sorted(copy.tags.values_list("name", flat=True)) == ["M6", "Steel"], "Links must be copied"
        assert set(copy.tags.values_list("release_id", flat=True)) == {new.pk}, "Links must point into new release"

    def test_create_release_leaves_source_links_untouched(self, release: Release, tagged_part: Part) -> None:
        release.lock()
        create_release("v2.0.0", release.version)
        assert set(tagged_part.tags.values_list("release_id", flat=True)) == {release.pk}, "Source links unchanged"
        assert tagged_part.tags.count() == 2, "Source part must keep its 2 tags"

    def test_create_release_without_links_succeeds(self, release: Release) -> None:
        Part.objects.create(name="Lonely", release=release)
        release.lock()
        new = create_release("v2.0.0", release.version)
        assert Part.objects.get(release=new).tags.count() == 0, "A part with no links must copy cleanly"

    def test_create_release_keeps_non_versioned_end_and_extra_fields(
        self, release: Release, supplier: Supplier
    ) -> None:
        part = Part.objects.create(name="Bolt", release=release)
        Certification.objects.create(part=part, supplier=supplier, level="gold")
        release.lock()
        new = create_release("v2.0.0", release.version)
        cert = Certification.objects.get(part__release=new)
        assert cert.supplier_id == supplier.pk, "Non-versioned end must stay the same object"
        assert cert.level == "gold", "Extra through fields must be copied"
        assert Certification.objects.count() == 2, "Source certification must remain"

    def test_create_release_copies_versioned_through_once(self, release: Release) -> None:
        part = Part.objects.create(name="Bolt", release=release)
        kit = Kit.objects.create(name="Starter", release=release)
        KitPart.objects.create(kit=kit, part=part, quantity=4, release=release)
        release.lock()
        new = create_release("v2.0.0", release.version)
        new_link = KitPart.objects.get(release=new)
        assert KitPart.objects.all_rows(new).count() == 1, "Versioned through rows must be copied exactly once"
        assert new_link.kit.release_id == new.pk and new_link.part.release_id == new.pk, "Both ends remapped"
        assert new_link.quantity == 4, "Through fields must be copied"

    def test_create_release_link_outside_source_release_raises(self, release: Release) -> None:
        other = Release.objects.create(version="v-other")
        part = Part.objects.create(name="Bolt", release=release)
        part.tags.add(Tag.objects.create(name="Foreign", release=other))
        release.lock()
        with pytest.raises(ValueError, match="not in the source release"):
            create_release("v2.0.0", release.version)
        assert not Release.objects.filter(version="v2.0.0").exists(), "Failed branch must roll back completely"


@pytest.mark.django_db
class TestManyToManyLockGuard:
    @pytest.mark.parametrize("deploy", [False, True], ids=["locked", "deployed"])
    @pytest.mark.parametrize("action", ["add", "remove", "clear", "set"])
    def test_change_links_of_frozen_row_raises(
        self, release: Release, tagged_part: Part, action: str, deploy: bool
    ) -> None:
        extra = Tag.objects.create(name="Extra", release=release)
        steel = tagged_part.tags.get(name="Steel")
        release.lock()
        if deploy:
            release.deploy()
        calls = {
            "add": lambda: tagged_part.tags.add(extra),
            "remove": lambda: tagged_part.tags.remove(steel),
            "clear": tagged_part.tags.clear,
            "set": lambda: tagged_part.tags.set([extra]),
        }
        with pytest.raises(ValidationError, match="is locked"), transaction.atomic():
            calls[action]()
        assert tagged_part.tags.count() == 2, "Links of a frozen row must stay unchanged"

    def test_reverse_side_change_raises(self, release: Release, tagged_part: Part) -> None:
        steel = tagged_part.tags.get(name="Steel")
        release.lock()
        with pytest.raises(ValidationError, match="is locked"), transaction.atomic():
            steel.parts.clear()
        assert tagged_part.tags.count() == 2, "Reverse clear must not unlink frozen rows"

    def test_through_model_link_to_frozen_row_raises(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="Bolt", release=release)
        release.lock()
        with pytest.raises(ValidationError, match="is locked"), transaction.atomic():
            part.certified_by.add(supplier, through_defaults={"level": "gold"})

    def test_change_links_of_unlocked_row_succeeds(self, release: Release, tagged_part: Part) -> None:
        tagged_part.tags.clear()
        assert tagged_part.tags.count() == 0, "Unlocked rows must still be editable"

    def test_cascade_into_links_of_frozen_row_raises(self, release: Release, supplier: Supplier) -> None:
        part = Part.objects.create(name="Bolt", release=release)
        Certification.objects.create(part=part, supplier=supplier, level="gold")
        release.lock()
        with pytest.raises(ValidationError, match="Certification rows of locked release"), transaction.atomic():
            supplier.delete()
        assert Certification.objects.filter(part=part).exists(), "Link of a frozen row must survive"


@pytest.mark.django_db
class TestDeleteReleaseWithManyToMany:
    def test_delete_release_removes_links(self, release: Release, tagged_part: Part, supplier: Supplier) -> None:
        Certification.objects.create(part=tagged_part, supplier=supplier, level="gold")
        release.lock()
        delete_release(release.version)
        assert not Part.tags.through.objects.exists(), "Auto through rows must be deleted"
        assert not Certification.objects.exists(), "Custom through rows must be deleted"
        assert Supplier.objects.filter(pk=supplier.pk).exists(), "Non-versioned end must survive"
