"""Item image HTTP views (spec 2026-10-26, I5/I6) against a real config-entry setup."""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from PIL import Image
from pytest_homeassistant_custom_component.typing import (  # type: ignore[import-untyped]
    ClientSessionGenerator,
)

from custom_components.simple_inventory.const import DOMAIN, FIELD_IMAGE, FIELD_NAME
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.storage import images
from custom_components.simple_inventory.storage.images import MAX_IMAGE_BYTES, ImageStore

from .harness import add_entry, integration_env, open_database, setup_entry

KITCHEN = "kitchen_entry"
GARAGE = "garage_entry"


def png(size: tuple[int, int] = (2048, 1024)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def url(item_id: str) -> str:
    return f"/api/simple_inventory/image/{item_id}"


def upload(data: bytes, field: str = "file") -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field(field, data, filename="photo.png", content_type="image/png")
    return form


@pytest.fixture
async def env(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> AsyncGenerator[dict[str, str], None]:
    """Kitchen (Milk, Rice) and Garage (Tools) set up for real; yields the item ids."""
    async with integration_env(hass, tmp_path) as hass_env:
        async with open_database(hass_env) as repository:
            await repository.upsert_inventory(KITCHEN, "Kitchen", entry_type="inventory")
            await repository.upsert_inventory(GARAGE, "Garage", entry_type="inventory")
            ids = {
                "milk": await repository.create_item(KITCHEN, {FIELD_NAME: "Milk"}),
                "rice": await repository.create_item(KITCHEN, {FIELD_NAME: "Rice"}),
                "tools": await repository.create_item(GARAGE, {FIELD_NAME: "Tools"}),
            }
        kitchen = add_entry(hass_env, KITCHEN, "Kitchen")
        add_entry(hass_env, GARAGE, "Garage")
        await setup_entry(hass_env, kitchen)
        yield ids


def coordinator(hass: HomeAssistant, inventory_id: str = KITCHEN) -> SimpleInventoryCoordinator:
    coordinators: dict[str, SimpleInventoryCoordinator] = hass.data[DOMAIN].coordinators
    return coordinators[inventory_id]


async def stored_image(hass: HomeAssistant, item_id: str) -> str:
    item = await coordinator(hass).repository.get_item_by_id(item_id)
    assert item is not None
    return str(item[FIELD_IMAGE])


def updated_events(hass: HomeAssistant, inventory_id: str = KITCHEN) -> list[Event]:
    seen: list[Event] = []

    @callback
    def _listener(event: Event) -> None:
        seen.append(event)

    hass.bus.async_listen(f"{DOMAIN}_updated_{inventory_id}", _listener)
    return seen


async def test_views_require_authentication(
    hass: HomeAssistant, env: dict[str, str], hass_client_no_auth: ClientSessionGenerator
) -> None:
    client = await hass_client_no_auth()

    for method in ("get", "post", "delete"):
        response = await client.request(method, url(env["milk"]))
        assert response.status == 401


async def test_upload_stores_resized_webp_and_serves_full_and_thumbnail(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    events = updated_events(hass)
    client = await hass_client()

    response = await client.post(url(env["milk"]), data=upload(png()))

    assert response.status == 200
    stamp = (await response.json())[FIELD_IMAGE]
    assert stamp and stamp == await stored_image(hass, env["milk"])
    await hass.async_block_till_done()
    assert events  # the item-updated path ran, so the card refreshes
    [listed] = [
        item
        for item in await coordinator(hass).async_list_items(KITCHEN)
        if item[FIELD_NAME] == "Milk"
    ]
    assert listed[FIELD_IMAGE] == stamp

    full = await client.get(url(env["milk"]), params={"v": stamp})
    assert full.status == 200
    assert full.headers["Content-Type"] == "image/webp"
    assert full.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(await full.read())).size == (1024, 512)

    thumb = await client.get(url(env["milk"]), params={"thumb": "1", "v": stamp})
    assert thumb.status == 200
    assert thumb.headers["Content-Type"] == "image/webp"
    assert Image.open(io.BytesIO(await thumb.read())).size == (128, 64)


async def test_tile_serves_the_tile_and_thumb_wins(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    stamp = (await (await client.post(url(env["milk"]), data=upload(png()))).json())[FIELD_IMAGE]

    tile = await client.get(url(env["milk"]), params={"tile": "1", "v": stamp})
    assert tile.status == 200
    assert tile.headers["Content-Type"] == "image/webp"
    assert tile.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(await tile.read())).size == (384, 192)

    both = await client.get(url(env["milk"]), params={"thumb": "1", "tile": "1", "v": stamp})
    assert Image.open(io.BytesIO(await both.read())).size == (128, 64)


async def test_missing_tile_is_built_from_the_full_image(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    await client.post(url(env["milk"]), data=upload(png()))
    tile_path = ImageStore(hass).path(env["milk"], "tile")
    tile_path.unlink()

    response = await client.get(url(env["milk"]), params={"tile": "1"})

    assert response.status == 200
    assert Image.open(io.BytesIO(await response.read())).size == (384, 192)
    assert tile_path.is_file()


async def test_tile_falls_back_to_the_full_file_when_it_cannot_be_built(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = await hass_client()
    await client.post(url(env["milk"]), data=upload(png()))
    store = ImageStore(hass)
    store.path(env["milk"], "tile").unlink()
    store.path(env["milk"], "full").write_bytes(b"corrupt")

    response = await client.get(url(env["milk"]), params={"tile": "1"})

    assert response.status == 200
    assert await response.read() == b"corrupt"
    assert "Could not create the tile image" in caplog.text


async def test_tile_falls_back_to_the_full_file_when_the_tile_cannot_be_written(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = await hass_client()
    await client.post(url(env["milk"]), data=upload(png()))
    store = ImageStore(hass)
    store.path(env["milk"], "tile").unlink()
    full = store.path(env["milk"], "full").read_bytes()

    with patch.object(images, "_replace_all", side_effect=OSError(28, "No space left")):
        response = await client.get(url(env["milk"]), params={"tile": "1"})

    assert response.status == 200
    assert await response.read() == full
    assert "Could not create the tile image" in caplog.text


async def test_get_without_image_is_404(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()

    for item_id in (env["rice"], "no-such-item"):
        response = await client.get(url(item_id), params={"thumb": "1"})
        assert response.status == 404
        assert await response.json() == {"code": "image_not_found"}


async def test_get_with_missing_file_is_404(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    await client.post(url(env["milk"]), data=upload(png()))
    ImageStore(hass).path(env["milk"], "full").unlink()

    response = await client.get(url(env["milk"]))

    assert response.status == 404
    assert await response.json() == {"code": "image_not_found"}


@pytest.mark.parametrize(
    "form",
    [
        upload(b"this is not an image"),
        upload(png(), field="photo"),
    ],
    ids=["not-an-image", "no-file-field"],
)
async def test_invalid_upload_is_400_and_keeps_the_item_unchanged(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    form: aiohttp.FormData,
) -> None:
    client = await hass_client()

    response = await client.post(url(env["milk"]), data=form)

    assert response.status == 400
    assert await response.json() == {"code": "image_invalid"}
    assert await stored_image(hass, env["milk"]) == ""


@pytest.mark.parametrize("content_type", ["image/png", "multipart/form-data"])
async def test_body_that_is_not_valid_multipart_is_400(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    content_type: str,
) -> None:
    client = await hass_client()

    response = await client.post(
        url(env["milk"]), data=png(), headers={"Content-Type": content_type}
    )

    assert response.status == 400
    assert await response.json() == {"code": "image_invalid"}


async def test_upload_over_10_mb_is_413(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()

    response = await client.post(url(env["milk"]), data=upload(b"\0" * (MAX_IMAGE_BYTES + 1)))

    assert response.status == 413
    assert await response.json() == {"code": "image_too_large"}
    assert await stored_image(hass, env["milk"]) == ""


async def test_upload_or_delete_for_unknown_or_unloaded_item_is_404(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    await hass.config_entries.async_unload(GARAGE)

    for item_id in ("no-such-item", env["tools"]):
        posted = await client.post(url(item_id), data=upload(png()))
        deleted = await client.delete(url(item_id))
        assert (posted.status, await posted.json()) == (404, {"code": "item_not_found"})
        assert (deleted.status, await deleted.json()) == (404, {"code": "item_not_found"})


async def test_delete_removes_files_and_is_idempotent(
    hass: HomeAssistant, env: dict[str, str], hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    await client.post(url(env["milk"]), data=upload(png()))
    store = ImageStore(hass)
    events = updated_events(hass)

    first = await client.delete(url(env["milk"]))
    second = await client.delete(url(env["milk"]))

    assert (first.status, await first.json()) == (200, {FIELD_IMAGE: ""})
    assert (second.status, await second.json()) == (200, {FIELD_IMAGE: ""})
    assert await stored_image(hass, env["milk"]) == ""
    assert not store.path(env["milk"], "full").exists()
    assert not store.path(env["milk"], "thumb").exists()
    await hass.async_block_till_done()
    assert len(events) == 1  # only the delete that changed something signals
    assert (await client.get(url(env["milk"]))).status == 404


async def test_delete_of_an_item_removed_meanwhile_is_404(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kitchen = coordinator(hass)

    async def _removed(inventory_id: str, item_id: str) -> None:
        raise kitchen._image_item_not_found(inventory_id, item_id)

    monkeypatch.setattr(kitchen, "async_clear_item_image", _removed)
    client = await hass_client()

    response = await client.delete(url(env["milk"]))

    assert (response.status, await response.json()) == (404, {"code": "item_not_found"})


async def test_non_admin_users_may_upload(
    hass: HomeAssistant,
    env: dict[str, str],
    hass_client: ClientSessionGenerator,
    hass_read_only_access_token: str,
) -> None:
    client = await hass_client(hass_read_only_access_token)

    response = await client.post(url(env["milk"]), data=upload(png((64, 64))))

    assert response.status == 200


# --- coordinator ------------------------------------------------------------------------


async def test_set_image_rejects_an_item_of_another_inventory(
    hass: HomeAssistant, env: dict[str, str]
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await coordinator(hass).async_set_item_image(KITCHEN, env["tools"], png((8, 8)))

    assert err.value.translation_key == "item_not_found"


async def test_item_removed_while_saving_leaves_no_files(
    hass: HomeAssistant, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    kitchen = coordinator(hass)

    async def _gone(item_id: str, data: dict[str, Any]) -> bool:
        return False

    monkeypatch.setattr(kitchen.repository, "update_item", _gone)
    with pytest.raises(ServiceValidationError) as err:
        await kitchen.async_set_item_image(KITCHEN, env["milk"], png((8, 8)))

    assert err.value.translation_key == "item_not_found"
    assert not ImageStore(hass).path(env["milk"], "full").exists()


async def test_clear_racing_a_set_never_leaves_a_stamp_without_files(
    hass: HomeAssistant, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clear reads the item (no photo yet), a set completes, then clear deletes the files."""
    kitchen = coordinator(hass)
    store = kitchen.images
    real_delete = store.async_delete
    clear_reached_delete = asyncio.Event()
    resume_clear = asyncio.Event()

    async def _paused_delete(item_id: str) -> None:
        clear_reached_delete.set()
        await resume_clear.wait()
        await real_delete(item_id)

    monkeypatch.setattr(store, "async_delete", _paused_delete)
    async with asyncio.timeout(5):
        clear = asyncio.ensure_future(kitchen.async_clear_item_image(KITCHEN, env["milk"]))
        await clear_reached_delete.wait()
        set_image = asyncio.ensure_future(
            kitchen.async_set_item_image(KITCHEN, env["milk"], png((8, 8)))
        )
        await asyncio.sleep(0.05)
        resume_clear.set()
        await asyncio.gather(clear, set_image)

    has_stamp = bool(await stored_image(hass, env["milk"]))
    assert store.path(env["milk"], "full").exists() == has_stamp
    assert store.path(env["milk"], "thumb").exists() == has_stamp
