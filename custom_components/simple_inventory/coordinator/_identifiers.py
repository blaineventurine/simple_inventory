"""Every item name and alias of one inventory, keyed as item resolution compares them."""

from __future__ import annotations

from collections.abc import Iterable

from ..const import match_key


class ItemIdentifiers:
    """Names and aliases by ``match_key``, each with the items that own them.

    Built from ``InventoryRepository.list_item_identifiers``; a caller writing several
    items (an import) keeps it current with ``set_item`` instead of re-reading it.
    Several items can share a key in data stored before the clash checks existed.
    """

    def __init__(self, rows: Iterable[tuple[str, str, str | None]]) -> None:
        self._names: dict[str, dict[str, str]] = {}
        self._aliases: dict[str, dict[str, str]] = {}
        self._items: dict[str, tuple[str, list[str]]] = {}
        for item_id, name, alias in rows:
            _name, aliases = self._items.setdefault(item_id, (name, []))
            if alias is not None:
                aliases.append(alias)
        for item_id, (name, aliases) in self._items.items():
            self._index(item_id, name, aliases)

    def _index(self, item_id: str, name: str, aliases: list[str]) -> None:
        self._names.setdefault(match_key(name), {})[item_id] = name
        for alias in aliases:
            self._aliases.setdefault(match_key(alias), {})[item_id] = name

    def set_item(self, item_id: str, name: str, aliases: list[str] | None = None) -> None:
        """Record *item_id*'s current name, and its aliases (``None``: unchanged)."""
        old_name, old_aliases = self._items.get(item_id, (name, []))
        for key, owners in (
            (match_key(old_name), self._names),
            *((match_key(alias), self._aliases) for alias in old_aliases),
        ):
            owners.get(key, {}).pop(item_id, None)
        new_aliases = old_aliases if aliases is None else list(aliases)
        self._items[item_id] = (name, new_aliases)
        self._index(item_id, name, new_aliases)

    def item_named(self, name: str) -> str | None:
        """The id of an item whose name matches *name*."""
        return next(iter(self._names.get(match_key(name), {})), None)

    def name_owner(self, value: str, exclude: str) -> str | None:
        """Name of an item other than *exclude* whose name matches *value*."""
        return _other(self._names.get(match_key(value), {}), exclude)

    def alias_owner(self, value: str, exclude: str) -> str | None:
        """Name of an item other than *exclude* with an alias matching *value*."""
        return _other(self._aliases.get(match_key(value), {}), exclude)

    def has_alias(self, item_id: str, value: str) -> bool:
        """Whether *item_id* already has an alias matching *value*."""
        return item_id in self._aliases.get(match_key(value), {})


def _other(owners: dict[str, str], exclude: str) -> str | None:
    return next((name for item_id, name in owners.items() if item_id != exclude), None)
