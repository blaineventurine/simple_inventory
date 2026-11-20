"""ItemIdentifiers: the name/alias index import keeps current while it writes."""

from __future__ import annotations

from custom_components.simple_inventory.coordinator._identifiers import ItemIdentifiers


def test_lookups_compare_like_item_resolution() -> None:
    index = ItemIdentifiers(
        [("oat", "Oatmeal", "Oats"), ("oat", "Oatmeal", "zob"), ("cok", "Čokolada", None)]
    )

    assert index.item_named(" čokolada ") == "cok"
    assert index.item_named("oats") is None
    assert index.name_owner("ČOKOLADA", exclude="oat") == "Čokolada"
    assert index.name_owner("čokolada", exclude="cok") is None
    assert index.alias_owner("OATS", exclude="cok") == "Oatmeal"
    assert index.has_alias("oat", "ZOB")
    assert not index.has_alias("cok", "zob")


def test_shared_keys_from_older_data_still_report_the_other_item() -> None:
    index = ItemIdentifiers([("a", "Čaj", None), ("b", "čaj", None)])

    assert index.name_owner("čaj", exclude="a") == "čaj"
    assert index.name_owner("čaj", exclude="b") == "Čaj"


def test_set_item_replaces_the_items_entries() -> None:
    index = ItemIdentifiers([("oat", "Oatmeal", "oats")])

    index.set_item("oat", "Oatmeal", ["porridge"])
    index.set_item("rice", "Rice", ["basmati"])
    index.set_item("rice", "Rice")

    assert index.alias_owner("oats", exclude="") is None
    assert index.alias_owner("porridge", exclude="") == "Oatmeal"
    assert index.alias_owner("basmati", exclude="") == "Rice"
    assert index.item_named("rice") == "rice"
