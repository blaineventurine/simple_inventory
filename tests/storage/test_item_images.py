"""Item images in storage (spec 2026-10-26, I1-I4, I9): ImageStore files, schema v6, hooks."""

from __future__ import annotations

import asyncio
import io
import os
import threading
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest
from homeassistant.core import HomeAssistant
from PIL import Image

from custom_components.simple_inventory.const import FIELD_IMAGE, FIELD_NAME
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.hub import InventoryHub
from custom_components.simple_inventory.storage import images
from custom_components.simple_inventory.storage.images import (
    MAX_IMAGE_BYTES,
    ImageInvalidError,
    ImageStore,
    ImageTooLargeError,
    async_delete_inventory_with_images,
    async_sweep_orphan_images,
)
from custom_components.simple_inventory.storage.repository import (
    SCHEMA_VERSION,
    InventoryRepository,
)

ORIENTATION = 0x0112
MAKE = 0x010F


def make_image(
    size: tuple[int, int] = (64, 48),
    fmt: str = "PNG",
    mode: str = "RGB",
    color: Any = (200, 30, 30),
    **save: Any,
) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format=fmt, **save)
    return buffer.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


@pytest.fixture
def store(hass_with_tmp_config: HomeAssistant) -> ImageStore:
    return ImageStore(hass_with_tmp_config)


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="images.db")
    await repository.async_initialize()
    await repository.upsert_inventory("inv", "Kitchen")
    await repository.upsert_inventory("other", "Garage")
    try:
        yield repository
    finally:
        await repository.async_close()


def stored_files(store: ImageStore) -> set[str]:
    return (
        {entry.name for entry in store.directory.iterdir()} if store.directory.is_dir() else set()
    )


# --- ImageStore -------------------------------------------------------------------------


def test_images_live_in_the_integration_folder_of_the_config_dir(
    store: ImageStore, tmp_path: Path
) -> None:
    assert store.directory == tmp_path / "simple_inventory" / "images"
    assert store.path("abc-1", "full") == store.directory / "abc-1.webp"
    assert store.path("abc-1", "tile") == store.directory / "abc-1_tile.webp"
    assert store.path("abc-1", "thumb") == store.directory / "abc-1_thumb.webp"


@pytest.mark.parametrize("item_id", ["", "../evil", "a/b", "a\\b", ".", "..", "x" * 65, "a b"])
def test_unsafe_item_ids_never_become_paths(store: ImageStore, item_id: str) -> None:
    with pytest.raises(ValueError):
        store.path(item_id, "full")


async def test_unsafe_item_id_is_rejected_before_anything_is_written(store: ImageStore) -> None:
    with pytest.raises(ValueError):
        await store.async_save_bytes("../evil", make_image())
    assert stored_files(store) == set()


async def test_save_writes_webp_full_image_and_thumbnail(store: ImageStore) -> None:
    stamp = await store.async_save_bytes("milk", make_image((3000, 1500), "PNG"))

    assert stamp
    assert stored_files(store) == {"milk.webp", "milk_tile.webp", "milk_thumb.webp"}
    full = decode(store.path("milk", "full").read_bytes())
    thumb = decode(store.path("milk", "thumb").read_bytes())
    assert (full.format, full.size, full.mode) == ("WEBP", (1024, 512), "RGB")
    assert (thumb.format, thumb.size) == ("WEBP", (128, 64))


async def test_save_writes_full_tile_and_thumbnail(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image((2000, 1500), "PNG"))

    sizes = {
        size: decode(store.path("milk", size).read_bytes()) for size in ("full", "tile", "thumb")
    }
    assert {size: (image.format, image.size) for size, image in sizes.items()} == {
        "full": ("WEBP", (1024, 768)),
        "tile": ("WEBP", (384, 288)),
        "thumb": ("WEBP", (128, 96)),
    }


async def test_small_images_are_not_upscaled(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image((50, 40), "JPEG"))

    for size in ("full", "tile", "thumb"):
        assert decode(store.path("milk", size).read_bytes()).size == (50, 40)


async def test_ensure_tile_builds_missing_tile_from_full_image(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image((2000, 1500)))
    store.path("milk", "tile").unlink()

    path = await store.async_ensure_tile("milk")

    assert path == store.path("milk", "tile")
    assert decode(path.read_bytes()).size == (384, 288)


async def test_ensure_tile_encodes_once_for_concurrent_requests(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image((2000, 1500)))
    store.path("milk", "tile").unlink()
    real_encode = images.encode_tile
    calls: list[bytes] = []

    def counting(full_webp: bytes) -> bytes:
        calls.append(full_webp)
        return real_encode(full_webp)

    with patch.object(images, "encode_tile", counting):
        first, second = await asyncio.gather(
            store.async_ensure_tile("milk"), store.async_ensure_tile("milk")
        )

    assert first == second == store.path("milk", "tile")
    assert len(calls) == 1


async def test_ensure_tile_without_full_image_returns_none(store: ImageStore) -> None:
    assert await store.async_ensure_tile("milk") is None


async def test_ensure_tile_refuses_a_full_slot_with_too_many_pixels(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image())
    store.path("milk", "tile").unlink()
    # 72 MP, but a few KB: a file the integration never writes (it stores <= 1024 px).
    store.path("milk", "full").write_bytes(make_image((9000, 8000), mode="1", color=0))

    with pytest.raises(ImageTooLargeError):
        await store.async_ensure_tile("milk")
    assert not store.path("milk", "tile").exists()


def test_encode_tile_maps_pillow_decompression_bombs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 64x48 is now over twice the limit

    with pytest.raises(ImageTooLargeError):
        images.encode_tile(make_image(fmt="WEBP"))


async def test_cancelled_tile_build_keeps_the_lock_until_the_file_is_written(
    hass_with_tmp_config: HomeAssistant, store: ImageStore
) -> None:
    """A save after a cancelled request waits for the orphaned build, so its tile wins."""
    await store.async_save_bytes("milk", make_image((300, 300), color=(255, 0, 0)))
    store.path("milk", "tile").unlink()
    real_encode = images.encode_tile
    started = threading.Event()
    release = threading.Event()

    def slow_encode(full_webp: bytes) -> bytes:
        started.set()
        release.wait(5)
        return real_encode(full_webp)

    with patch.object(images, "encode_tile", slow_encode):
        request = asyncio.ensure_future(store.async_ensure_tile("milk"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        request.cancel()
        save = asyncio.ensure_future(
            store.async_save_bytes("milk", make_image((300, 300), color=(0, 0, 255)))
        )
        await asyncio.sleep(0.05)
        assert not save.done()
        release.set()
        await save
        with pytest.raises(asyncio.CancelledError):
            await request
        await hass_with_tmp_config.async_block_till_done()

    tile = decode(store.path("milk", "tile").read_bytes()).convert("RGB")
    red, _, blue = tile.getpixel((5, 5))  # type: ignore[misc]
    assert red < 50 and blue > 200  # the new (blue) photo, not the cancelled build's red
    assert images._ITEM_LOCKS == {}


async def test_exif_orientation_is_applied_and_metadata_stripped(store: ImageStore) -> None:
    exif = Image.Exif()
    exif[ORIENTATION] = 6  # stored landscape, displayed rotated 90 degrees: portrait
    exif[MAKE] = "SecretCam"
    await store.async_save_bytes("milk", make_image((200, 100), "JPEG", exif=exif.tobytes()))

    for size in ("full", "tile", "thumb"):
        image = decode(store.path("milk", size).read_bytes())
        assert image.height > image.width
        assert not image.getexif()
        assert not {"exif", "xmp", "icc_profile"} & set(image.info)
    assert b"SecretCam" not in store.path("milk", "full").read_bytes()


async def test_transparency_is_kept(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image(mode="RGBA", color=(0, 0, 255, 0)))

    image = decode(store.path("milk", "full").read_bytes())
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # type: ignore[index]


async def test_animated_gif_keeps_the_first_frame(store: ImageStore) -> None:
    frames = [Image.new("RGB", (32, 32), color) for color in ((255, 0, 0), (0, 0, 255))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    await store.async_save_bytes("milk", buffer.getvalue())

    red, green, blue = decode(store.path("milk", "full").read_bytes()).getpixel((16, 16))  # type: ignore[misc]
    assert red > 200 and blue < 50


@pytest.mark.parametrize(
    "data",
    [
        b"definitely not an image",
        make_image(fmt="BMP"),
        make_image((64, 64), "JPEG")[:200],
    ],
    ids=["garbage", "unsupported-format", "truncated"],
)
async def test_invalid_data_is_rejected_and_nothing_written(store: ImageStore, data: bytes) -> None:
    with pytest.raises(ImageInvalidError):
        await store.async_save_bytes("milk", data)
    assert stored_files(store) == set()


async def test_more_than_10_mb_is_too_large(store: ImageStore) -> None:
    with pytest.raises(ImageTooLargeError):
        await store.async_save_bytes("milk", b"\0" * (MAX_IMAGE_BYTES + 1))
    assert stored_files(store) == set()


async def test_too_many_pixels_is_too_large(
    store: ImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageTooLargeError):
        await store.async_save_bytes("milk", make_image((11, 10)))


async def test_more_pixels_than_pillow_allows_is_too_large(
    store: ImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pillow itself refuses (DecompressionBombError) above twice its own pixel limit.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImageTooLargeError):
        await store.async_save_bytes("milk", make_image((11, 10)))
    assert stored_files(store) == set()


async def test_every_save_returns_a_new_stamp_and_replaces_the_files(store: ImageStore) -> None:
    first = await store.async_save_bytes("milk", make_image((300, 300)))
    second = await store.async_save_bytes("milk", make_image((300, 150)))

    assert first != second
    assert stored_files(store) == {"milk.webp", "milk_tile.webp", "milk_thumb.webp"}
    assert decode(store.path("milk", "full").read_bytes()).size == (300, 150)


async def test_failed_write_leaves_previous_files_and_no_temp_file(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image((300, 300)))
    before = store.path("milk", "full").read_bytes()

    with (
        patch.object(images.os, "replace", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        await store.async_save_bytes("milk", make_image((300, 150)))

    assert stored_files(store) == {"milk.webp", "milk_tile.webp", "milk_thumb.webp"}
    assert store.path("milk", "full").read_bytes() == before


async def test_failed_second_file_write_keeps_the_previous_pair(
    store: ImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both new files are written before either replaces an old one."""
    await store.async_save_bytes("milk", make_image((300, 300)))
    before = (store.path("milk", "full").read_bytes(), store.path("milk", "thumb").read_bytes())
    real_fdopen = images.os.fdopen
    opened: list[int] = []

    def fail_second_write(fd: int, *args: Any) -> Any:
        opened.append(fd)
        if len(opened) == 2:
            os.close(fd)
            raise OSError("disk full")
        return real_fdopen(fd, *args)

    monkeypatch.setattr(images.os, "fdopen", fail_second_write)
    with pytest.raises(OSError, match="disk full"):
        await store.async_save_bytes("milk", make_image((300, 150)))

    assert stored_files(store) == {"milk.webp", "milk_tile.webp", "milk_thumb.webp"}
    after = (store.path("milk", "full").read_bytes(), store.path("milk", "thumb").read_bytes())
    assert after == before


async def test_concurrent_saves_of_one_item_never_mix_full_image_and_thumbnail(
    store: ImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writes are serialized per item: the full image and thumbnail come from the same save."""
    red = make_image((300, 300), color=(255, 0, 0))
    blue = make_image((300, 300), color=(0, 0, 255))
    real_replace = images.os.replace
    started = threading.Event()
    release = threading.Event()

    def slow_replace(source: str, target: Path) -> None:
        real_replace(source, target)
        if not started.is_set():
            # First save: pause between replacing its first and its second file.
            started.set()
            release.wait(5)

    monkeypatch.setattr(images.os, "replace", slow_replace)
    first = asyncio.ensure_future(store.async_save_bytes("milk", red))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
    second = asyncio.ensure_future(store.async_save_bytes("milk", blue))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(first, second)

    full = decode(store.path("milk", "full").read_bytes()).convert("RGB").getpixel((5, 5))
    thumb = decode(store.path("milk", "thumb").read_bytes()).convert("RGB").getpixel((5, 5))
    assert (full[0] > 200, full[2] > 200) == (thumb[0] > 200, thumb[2] > 200)  # type: ignore[index]
    assert images._ITEM_LOCKS == {}


async def test_lock_spans_caller_steps_and_is_reentrant(store: ImageStore) -> None:
    """A caller holding the item lock may save; other tasks wait until it is released."""
    async with asyncio.timeout(5), store.lock("milk"):
        await store.async_save_bytes("milk", make_image())
        delete = asyncio.ensure_future(store.async_delete("milk"))
        await asyncio.sleep(0.05)
        assert not delete.done()
        assert store.path("milk", "full").exists()
    await delete

    assert stored_files(store) == set()
    assert images._ITEM_LOCKS == {}


async def test_delete_removes_all_three_files_and_is_idempotent(store: ImageStore) -> None:
    await store.async_save_bytes("milk", make_image())
    await store.async_save_bytes("rice", make_image())

    await store.async_delete("milk")
    await store.async_delete("milk")

    assert stored_files(store) == {"rice.webp", "rice_tile.webp", "rice_thumb.webp"}


async def test_delete_failure_is_logged_not_raised(
    store: ImageStore, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(images, "_unlink_all", side_effect=OSError("busy")):
        await store.async_delete("milk")
    assert "Could not delete item image files" in caplog.text


async def test_sweep_keeps_only_images_of_the_given_items(store: ImageStore) -> None:
    for item_id in ("keep", "gone", "x_thumb", "y_tile"):
        await store.async_save_bytes(item_id, make_image())
    (store.directory / ".tmp-abc").write_bytes(b"partial")
    (store.directory / "notes.txt").write_text("junk")

    removed = await store.async_sweep({"keep", "x_thumb", "y_tile"})

    assert removed == 5
    assert stored_files(store) == {
        "keep.webp",
        "keep_tile.webp",
        "keep_thumb.webp",
        "x_thumb.webp",
        "x_thumb_tile.webp",
        "x_thumb_thumb.webp",
        "y_tile.webp",
        "y_tile_tile.webp",
        "y_tile_thumb.webp",
    }


async def test_sweep_without_folder_is_a_no_op(store: ImageStore) -> None:
    assert await store.async_sweep(set()) == 0


# --- Repository: schema v6 --------------------------------------------------------------


async def _image_column(conn: aiosqlite.Connection) -> tuple[Any, ...] | None:
    cursor = await conn.execute("PRAGMA table_info(items)")
    rows = await cursor.fetchall()
    await cursor.close()
    return next((tuple(row) for row in rows if row[1] == "image"), None)


async def test_fresh_database_has_image_column(repo: InventoryRepository) -> None:
    assert SCHEMA_VERSION == 6
    column = await _image_column(repo._connection())
    assert column is not None
    assert column[2:5] == ("TEXT", 1, "''")
    assert await repo.get_metadata_value("schema_version") == "6"


async def test_v5_database_migrates_to_v6_with_empty_images(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    path = Path(hass_with_tmp_config.config.path("v5.db"))
    repo = InventoryRepository(hass_with_tmp_config, db_filename="v5.db")
    await repo.async_initialize()
    await repo.upsert_inventory("inv", "Kitchen")
    milk_id = await repo.create_item("inv", {FIELD_NAME: "Milk"})
    await repo.async_close()

    async with aiosqlite.connect(path) as db:
        await db.execute("ALTER TABLE items DROP COLUMN image")
        await db.execute("UPDATE metadata SET value = '5' WHERE key = 'schema_version'")
        await db.commit()
        assert await _image_column(db) is None

    repo = InventoryRepository(hass_with_tmp_config, db_filename="v5.db")
    await repo.async_initialize()
    try:
        assert await repo.get_metadata_value("schema_version") == "6"
        column = await _image_column(repo._connection())
        assert column is not None and column[2:5] == ("TEXT", 1, "''")
        item = await repo.get_item_by_id(milk_id)
        assert item is not None and item[FIELD_IMAGE] == ""

        assert await repo.update_item(milk_id, {FIELD_IMAGE: "stamp1"})
        await repo._migrate_to_v6()
        item = await repo.get_item_by_id(milk_id)
        assert item is not None and item[FIELD_IMAGE] == "stamp1"
    finally:
        await repo.async_close()


async def test_every_item_reader_returns_image(repo: InventoryRepository) -> None:
    item_id = await repo.create_item("inv", {FIELD_NAME: "Milk"})
    assert (await repo.get_item_by_id(item_id) or {})[FIELD_IMAGE] == ""
    await repo.update_item(item_id, {FIELD_IMAGE: "stamp1"})
    await repo.set_item_barcodes(item_id, "inv", ["0123456789012"])

    by_name = await repo.get_item_by_name("inv", "milk")
    by_id = await repo.get_item_by_id(item_id)
    by_barcode = await repo.get_item_by_barcode("inv", "0123456789012")
    [global_hit] = await repo.get_item_by_barcode_global("0123456789012")
    [listed] = await repo.list_items_with_details("inv")

    for item in (by_name, by_id, by_barcode, global_hit, listed):
        assert item is not None
        assert item[FIELD_IMAGE] == "stamp1"
        assert item["icon"] == ""
    assert global_hit["inventory_name"] == "Kitchen"


async def test_list_item_ids_with_images(repo: InventoryRepository) -> None:
    milk = await repo.create_item("inv", {FIELD_NAME: "Milk"})
    await repo.create_item("inv", {FIELD_NAME: "Rice"})
    tools = await repo.create_item("other", {FIELD_NAME: "Tools"})
    await repo.update_item(milk, {FIELD_IMAGE: "s1"})
    await repo.update_item(tools, {FIELD_IMAGE: "s2"})

    assert await repo.list_item_ids_with_images() == {milk, tools}
    assert await repo.list_item_ids_with_images("inv") == {milk}


# --- Removal hooks and startup sweep (I9) -----------------------------------------------


async def _item_with_image(
    repo: InventoryRepository, store: ImageStore, inventory_id: str, name: str
) -> str:
    item_id = await repo.create_item(inventory_id, {FIELD_NAME: name})
    stamp = await store.async_save_bytes(item_id, make_image())
    await repo.update_item(item_id, {FIELD_IMAGE: stamp})
    return item_id


async def test_remove_item_deletes_its_image_files(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository, store: ImageStore
) -> None:
    entry = MagicMock()
    entry.entry_id = "inv"
    coordinator = SimpleInventoryCoordinator(
        hass_with_tmp_config, entry, repo, InventoryHub(hass_with_tmp_config, repo)
    )
    milk = await _item_with_image(repo, store, "inv", "Milk")
    rice = await _item_with_image(repo, store, "inv", "Rice")

    assert await coordinator.async_remove_item("inv", "Milk")

    assert stored_files(store) == {f"{rice}.webp", f"{rice}_tile.webp", f"{rice}_thumb.webp"}
    assert not store.path(milk, "full").exists()


async def test_deleting_an_inventory_deletes_its_items_images(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository, store: ImageStore
) -> None:
    await _item_with_image(repo, store, "inv", "Milk")
    tools = await _item_with_image(repo, store, "other", "Tools")

    assert await async_delete_inventory_with_images(hass_with_tmp_config, repo, "inv")

    assert await repo.fetch_inventory("inv") is None
    assert stored_files(store) == {f"{tools}.webp", f"{tools}_tile.webp", f"{tools}_thumb.webp"}


async def test_startup_sweep_removes_files_without_an_item_image(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository, store: ImageStore
) -> None:
    kept = await _item_with_image(repo, store, "inv", "Milk")
    cleared = await _item_with_image(repo, store, "inv", "Rice")
    await repo.update_item(cleared, {FIELD_IMAGE: ""})
    await store.async_save_bytes("deleted-item", make_image())

    await async_sweep_orphan_images(hass_with_tmp_config, repo)

    assert stored_files(store) == {f"{kept}.webp", f"{kept}_tile.webp", f"{kept}_thumb.webp"}


async def test_startup_sweep_logs_file_errors(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(ImageStore, "async_sweep", side_effect=OSError("denied")):
        await async_sweep_orphan_images(hass_with_tmp_config, repo)
    assert "Could not clean up item images" in caplog.text
