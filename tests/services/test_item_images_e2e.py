"""Item image services end to end (spec 2026-10-26, I7/I8): services -> coordinator -> files."""

from __future__ import annotations

import io
import os
from collections.abc import Generator
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from PIL import Image
from pytest_homeassistant_custom_component.test_util.aiohttp import (  # type: ignore[import-untyped]
    AiohttpClientMocker,
)

from custom_components.simple_inventory.const import FIELD_IMAGE
from custom_components.simple_inventory.coordinator import _images
from custom_components.simple_inventory.storage.images import MAX_IMAGE_BYTES, ImageStore

from ..harness import TodoStack

PHOTO_URL = "https://images.example.org/milk.jpg"


def jpeg(size: tuple[int, int] = (1600, 1200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (240, 240, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


def found(image_url: str | None, provider: str = "openfoodfacts") -> dict[str, Any]:
    product: dict[str, Any] = {"name": "Milk"}
    if image_url is not None:
        product["image_url"] = image_url
    return {"provider": provider, "found": True, "product": product}


@pytest.fixture
def lookup() -> Generator[AsyncMock, None, None]:
    """The configured product lookup; returns a photo URL for every barcode by default."""
    with patch.object(
        _images,
        "async_lookup_barcode_all_providers",
        new=AsyncMock(return_value=[found(PHOTO_URL)]),
    ) as mock:
        yield mock


async def _add_milk(stack: TodoStack, barcode: str | None = "5000000000002, 4000000000001") -> str:
    data: dict[str, Any] = {"inventory_id": "kitchen", "name": "Milk"}
    if barcode is not None:
        data["barcode"] = barcode
    await stack.call("add_item", **data)
    item = await stack.item("kitchen", "Milk")
    assert item is not None
    return str(item["id"])


async def _image(stack: TodoStack, name: str = "Milk") -> str:
    item = await stack.item("kitchen", name)
    assert item is not None
    return str(item[FIELD_IMAGE])


async def _error_key(stack: TodoStack, service: str, **data: Any) -> str | None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call(service, inventory_id="kitchen", **data)
    return err.value.translation_key


# --- set_item_image_from_barcode --------------------------------------------------------


async def test_product_photo_of_the_first_barcode_becomes_the_item_image(
    todo_stack: TodoStack, lookup: AsyncMock, aioclient_mock: AiohttpClientMocker
) -> None:
    item_id = await _add_milk(todo_stack)
    aioclient_mock.get(PHOTO_URL, content=jpeg())

    await todo_stack.call("set_item_image_from_barcode", inventory_id="kitchen", name="milk")

    lookup.assert_awaited_once_with(todo_stack.hass, "4000000000001")
    assert aioclient_mock.call_count == 1
    stamp = await _image(todo_stack)
    assert stamp
    [listed] = await todo_stack.coordinators["kitchen"].async_list_items("kitchen")
    assert listed[FIELD_IMAGE] == stamp
    full = Image.open(ImageStore(todo_stack.hass).path(item_id, "full"))
    assert (full.format, full.size) == ("WEBP", (1024, 768))


async def test_lookup_barcode_must_belong_to_the_item(
    todo_stack: TodoStack, lookup: AsyncMock, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_milk(todo_stack)
    aioclient_mock.get(PHOTO_URL, content=jpeg())

    await todo_stack.call(
        "set_item_image_from_barcode",
        inventory_id="kitchen",
        barcode="4000000000001",
        lookup_barcode="5000000000002",
    )
    lookup.assert_awaited_once_with(todo_stack.hass, "5000000000002")

    lookup.reset_mock()
    key = await _error_key(
        todo_stack, "set_item_image_from_barcode", name="Milk", lookup_barcode="9999999999999"
    )
    assert key == "barcode_not_on_item"
    lookup.assert_not_awaited()
    assert aioclient_mock.call_count == 1


async def test_item_without_barcode_or_lookup_without_photo_is_image_not_found(
    todo_stack: TodoStack, lookup: AsyncMock, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_milk(todo_stack, barcode=None)
    assert await _error_key(todo_stack, "set_item_image_from_barcode", name="Milk") == (
        "image_not_found"
    )
    lookup.assert_not_awaited()

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", barcode="111"
    )
    for results in (
        [found(None)],
        [{"provider": "openfoodfacts", "found": False}],
        [found("   ")],
    ):
        lookup.return_value = results
        assert await _error_key(todo_stack, "set_item_image_from_barcode", name="Milk") == (
            "image_not_found"
        )
    assert aioclient_mock.call_count == 0
    assert await _image(todo_stack) == ""


async def test_first_provider_with_a_photo_wins(
    todo_stack: TodoStack, lookup: AsyncMock, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_milk(todo_stack)
    lookup.return_value = [
        found(None),
        found("https://images.example.org/second.jpg", "upcitemdb"),
    ]
    aioclient_mock.get("https://images.example.org/second.jpg", content=jpeg((64, 64)))

    await todo_stack.call("set_item_image_from_barcode", inventory_id="kitchen", name="Milk")

    assert await _image(todo_stack)


@pytest.mark.parametrize(
    "image_url", ["file:///etc/passwd", "ftp://images.example.org/milk.jpg", "not a url"]
)
async def test_only_http_photo_urls_are_fetched(
    todo_stack: TodoStack,
    lookup: AsyncMock,
    aioclient_mock: AiohttpClientMocker,
    image_url: str,
) -> None:
    await _add_milk(todo_stack)
    lookup.return_value = [found(image_url)]

    key = await _error_key(todo_stack, "set_item_image_from_barcode", name="Milk")

    assert key == "image_download_failed"
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("response", "key"),
    [
        ({"status": HTTPStatus.NOT_FOUND}, "image_download_failed"),
        ({"exc": TimeoutError()}, "image_download_failed"),
        ({"exc": aiohttp.ClientConnectionError()}, "image_download_failed"),
        ({"content": b"\0" * (MAX_IMAGE_BYTES + 1)}, "image_too_large"),
        ({"content": b"<html>not a photo</html>"}, "image_invalid"),
    ],
    ids=["http-404", "timeout", "connection-error", "over-10-mb", "not-an-image"],
)
async def test_failed_download_keeps_the_previous_image(
    todo_stack: TodoStack,
    lookup: AsyncMock,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
    key: str,
) -> None:
    item_id = await _add_milk(todo_stack)
    previous = await todo_stack.coordinators["kitchen"].async_set_item_image(
        "kitchen", item_id, jpeg((32, 32))
    )
    aioclient_mock.get(PHOTO_URL, **response)

    assert await _error_key(todo_stack, "set_item_image_from_barcode", name="Milk") == key
    assert await _image(todo_stack) == previous


def test_download_limits() -> None:
    assert _images._DOWNLOAD_TIMEOUT == aiohttp.ClientTimeout(total=10)
    assert MAX_IMAGE_BYTES == 10 * 1024 * 1024


# --- set_item_image_from_media ----------------------------------------------------------


@pytest.fixture
async def media_dir(todo_stack: TodoStack, tmp_path: Path) -> Path:
    """A local media folder served by the real media_source integration."""
    directory = tmp_path / "media"
    directory.mkdir()
    todo_stack.hass.config.media_dirs = {"local": str(directory)}
    assert await async_setup_component(todo_stack.hass, "media_source", {})
    return directory


def _media_id(path: str) -> str:
    return f"media-source://media_source/local/{path}"


async def test_local_media_file_becomes_the_item_image(
    todo_stack: TodoStack, media_dir: Path
) -> None:
    item_id = await _add_milk(todo_stack)
    (media_dir / "pantry").mkdir()
    (media_dir / "pantry" / "milk.jpg").write_bytes(jpeg((300, 600)))

    await todo_stack.call(
        "set_item_image_from_media",
        inventory_id="kitchen",
        name="Milk",
        media_content_id=_media_id("pantry/milk.jpg"),
    )

    assert await _image(todo_stack)
    thumb = Image.open(ImageStore(todo_stack.hass).path(item_id, "thumb"))
    assert thumb.size == (64, 128)


async def test_media_outside_the_local_media_folders_is_unsupported(
    todo_stack: TodoStack, media_dir: Path, tmp_path: Path
) -> None:
    await _add_milk(todo_stack)
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(jpeg((16, 16)))
    os.symlink(secret, media_dir / "link.jpg")
    (media_dir / "folder.jpg").mkdir()

    for media_content_id in (
        _media_id("../secret.jpg"),
        _media_id("link.jpg"),
        _media_id("missing.jpg"),
        _media_id("folder.jpg"),
        "media-source://media_source/other/milk.jpg",
        "media-source://camera/camera.kitchen",
    ):
        key = await _error_key(
            todo_stack, "set_item_image_from_media", name="Milk", media_content_id=media_content_id
        )
        assert key == "unsupported_media_source", media_content_id
    assert await _image(todo_stack) == ""


async def test_media_file_over_10_mb_is_too_large(todo_stack: TodoStack, media_dir: Path) -> None:
    await _add_milk(todo_stack)
    with (media_dir / "huge.jpg").open("wb") as handle:
        handle.truncate(MAX_IMAGE_BYTES + 1)

    key = await _error_key(
        todo_stack, "set_item_image_from_media", name="Milk", media_content_id=_media_id("huge.jpg")
    )

    assert key == "image_too_large"


async def test_media_without_media_source_is_unsupported(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)

    key = await _error_key(
        todo_stack, "set_item_image_from_media", name="Milk", media_content_id=_media_id("a.jpg")
    )

    assert key == "unsupported_media_source"


# HA's image_upload stores each upload as <config>/image/<secrets.token_hex(16)>/original.
UPLOAD_ID = "0123456789abcdef0123456789abcdef"


def _upload_id(image_id: str) -> str:
    return f"media-source://image_upload/{image_id}"


def _store_upload(tmp_path: Path, image_id: str, data: bytes) -> Path:
    folder = tmp_path / "image" / image_id
    folder.mkdir(parents=True)
    original = folder / "original"
    original.write_bytes(data)
    return original


async def test_uploaded_image_becomes_the_item_image(todo_stack: TodoStack, tmp_path: Path) -> None:
    item_id = await _add_milk(todo_stack)
    _store_upload(tmp_path, UPLOAD_ID, jpeg((300, 600)))

    await todo_stack.call(
        "set_item_image_from_media",
        inventory_id="kitchen",
        name="Milk",
        media_content_id=_upload_id(UPLOAD_ID),
    )

    assert await _image(todo_stack)
    thumb = Image.open(ImageStore(todo_stack.hass).path(item_id, "thumb"))
    assert thumb.size == (64, 128)


async def test_uploaded_image_outside_the_upload_folder_is_unsupported(
    todo_stack: TodoStack, tmp_path: Path
) -> None:
    await _add_milk(todo_stack)
    _store_upload(tmp_path, UPLOAD_ID, jpeg((16, 16)))
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(jpeg((16, 16)))
    linked = tmp_path / "image" / ("1" * 32)
    linked.mkdir()
    os.symlink(secret, linked / "original")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "original").write_bytes(jpeg((16, 16)))
    os.symlink(outside, tmp_path / "image" / ("2" * 32))
    (tmp_path / "image" / ("3" * 32) / "original").mkdir(parents=True)

    for image_id in (
        "1" * 32,  # original is a symlink out of the folder
        "2" * 32,  # the id folder is a symlink out of the folder
        "3" * 32,  # original is a directory
        "4" * 32,  # no such upload
        UPLOAD_ID.upper(),
        UPLOAD_ID[:-1],
        f"{UPLOAD_ID}/original",
        f"{UPLOAD_ID}\n",
        "../secret.jpg",
        "..",
        "",
    ):
        key = await _error_key(
            todo_stack,
            "set_item_image_from_media",
            name="Milk",
            media_content_id=_upload_id(image_id),
        )
        assert key == "unsupported_media_source", image_id
    assert await _image(todo_stack) == ""


async def test_uploaded_image_over_10_mb_is_too_large(
    todo_stack: TodoStack, tmp_path: Path
) -> None:
    await _add_milk(todo_stack)
    original = _store_upload(tmp_path, UPLOAD_ID, b"")
    with original.open("wb") as handle:
        handle.truncate(MAX_IMAGE_BYTES + 1)

    key = await _error_key(
        todo_stack,
        "set_item_image_from_media",
        name="Milk",
        media_content_id=_upload_id(UPLOAD_ID),
    )

    assert key == "image_too_large"


# --- clear_item_image and item resolution -----------------------------------------------


async def test_clear_item_image_by_barcode_removes_the_files(todo_stack: TodoStack) -> None:
    item_id = await _add_milk(todo_stack)
    await todo_stack.coordinators["kitchen"].async_set_item_image("kitchen", item_id, jpeg())
    store = ImageStore(todo_stack.hass)

    await todo_stack.call("clear_item_image", inventory_id="kitchen", barcode="5000000000002")
    await todo_stack.call("clear_item_image", inventory_name="Kitchen", name="Milk")

    assert await _image(todo_stack) == ""
    assert not store.path(item_id, "full").exists()
    assert not store.path(item_id, "thumb").exists()


async def test_image_services_need_an_exact_item_name(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)

    assert await _error_key(todo_stack, "clear_item_image", name="Mil") == "item_not_found"
    assert await _error_key(todo_stack, "clear_item_image", barcode="000") == "barcode_not_found"
