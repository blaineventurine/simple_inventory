"""Item photos on disk (spec 2026-10-26, I1-I3, I9).

Each item with a photo owns three files under ``<config>/simple_inventory/images/``:
``<item_id>.webp`` (long edge <= 1024px), ``<item_id>_tile.webp`` (<= 384px, for tiles) and
``<item_id>_thumb.webp`` (<= 128px, for lists). Every source goes through
:meth:`ImageStore.async_save_bytes`: Pillow decodes the bytes, applies the EXIF orientation
and re-encodes to WebP without metadata. Files are written to a temp
file and renamed into place, so readers never see a partial image.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import tempfile
import time
from collections.abc import AsyncIterator, Collection, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from homeassistant.core import HomeAssistant
from PIL import Image, ImageOps, UnidentifiedImageError

from ..const import DOMAIN

if TYPE_CHECKING:
    from .repository import InventoryRepository

_LOGGER = logging.getLogger(__name__)

MAX_IMAGE_BYTES: Final = 10 * 1024 * 1024
FULL_EDGE: Final = 1024
TILE_EDGE: Final = 384
THUMB_EDGE: Final = 128
# Decompression-bomb guard: refuse to decode more pixels than a 64 MP photo.
MAX_IMAGE_PIXELS: Final = 64_000_000
_WEBP_QUALITY: Final = 82
# Pillow format names accepted as input; HEIF/AVIF only decode when Pillow supports them.
_ALLOWED_FORMATS: Final = frozenset({"JPEG", "MPO", "PNG", "WEBP", "GIF", "HEIF", "AVIF"})
_SAFE_ITEM_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_FULL_SUFFIX: Final = ".webp"
_TILE_SUFFIX: Final = "_tile.webp"
_THUMB_SUFFIX: Final = "_thumb.webp"
ImageSize = Literal["full", "tile", "thumb"]
_SUFFIXES: Final[dict[ImageSize, str]] = {
    "full": _FULL_SUFFIX,
    "tile": _TILE_SUFFIX,
    "thumb": _THUMB_SUFFIX,
}
_TEMP_PREFIX: Final = ".tmp-"


class _ItemLock:
    """An item's lock, the task holding it and how many tasks hold or wait for it."""

    __slots__ = ("lock", "owner", "users")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.owner: asyncio.Task[object] | None = None
        self.users = 0


# One lock per item id while an image change is pending, so concurrent changes of the same
# item cannot interleave their files (or, for callers holding it, their database update);
# removed again once idle.
_ITEM_LOCKS: dict[str, _ItemLock] = {}


@asynccontextmanager
async def _item_lock(item_id: str) -> AsyncIterator[None]:
    """Serialize the image changes of *item_id*; re-entrant within the holding task."""
    task = asyncio.current_task()
    entry = _ITEM_LOCKS.get(item_id)
    if entry is not None and entry.owner is task:
        yield
        return
    if entry is None:
        entry = _ITEM_LOCKS[item_id] = _ItemLock()
    entry.users += 1
    try:
        async with entry.lock:
            entry.owner = task
            try:
                yield
            finally:
                entry.owner = None
    finally:
        entry.users -= 1
        if not entry.users:
            del _ITEM_LOCKS[item_id]


class ImageError(Exception):
    """An image could not be stored."""


class ImageInvalidError(ImageError):
    """The data is not a decodable image in an accepted format."""


class ImageTooLargeError(ImageError):
    """The data exceeds MAX_IMAGE_BYTES, or the image exceeds MAX_IMAGE_PIXELS."""


def encode_image(data: bytes) -> tuple[bytes, bytes, bytes]:
    """Return ``(full, tile, thumbnail)`` WebP bytes for *data* (blocking; run in the executor).

    The EXIF orientation is applied, transparency is kept (RGBA) and every other mode
    becomes RGB. Only the first frame of an animation is used. No metadata is written.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageTooLargeError(f"{len(data)} bytes exceeds {MAX_IMAGE_BYTES}")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in _ALLOWED_FORMATS:
                raise ImageInvalidError(f"unsupported image format {source.format}")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ImageTooLargeError(f"{source.width}x{source.height} pixels")
            # JPEG only: decode at the smallest scale still >= FULL_EDGE (fast, low memory).
            source.draft("RGB", (FULL_EDGE, FULL_EDGE))
            image = ImageOps.exif_transpose(source)
            mode = "RGBA" if image.has_transparency_data else "RGB"
            if image.mode != mode:
                image = image.convert(mode)
            image.thumbnail((FULL_EDGE, FULL_EDGE), Image.Resampling.LANCZOS)
            tile = image.copy()
            tile.thumbnail((TILE_EDGE, TILE_EDGE), Image.Resampling.LANCZOS)
            thumb = tile.copy()
            thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
            return _webp(image), _webp(tile), _webp(thumb)
    except ImageError:
        raise
    except Image.DecompressionBombError as err:
        raise ImageTooLargeError(str(err)) from err
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise ImageInvalidError(str(err)) from err


def encode_tile(full_webp: bytes) -> bytes:
    """Tile-size WebP from a stored full image (blocking; for photos saved before tiles)."""
    try:
        with Image.open(io.BytesIO(full_webp)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ImageTooLargeError(f"{source.width}x{source.height} pixels")
            image = source.copy()
    except Image.DecompressionBombError as err:
        raise ImageTooLargeError(str(err)) from err
    image.thumbnail((TILE_EDGE, TILE_EDGE), Image.Resampling.LANCZOS)
    return _webp(image)


def _webp(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=_WEBP_QUALITY, method=4)
    return buffer.getvalue()


def _write_temp(directory: Path, data: bytes) -> Path:
    """Write *data* to a new temp file in *directory* (same file system as the target)."""
    fd, temp_name = tempfile.mkstemp(dir=directory, prefix=_TEMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return Path(temp_name)


def _replace_all(files: list[tuple[Path, bytes]]) -> None:
    """Write every ``(target, data)`` to a temp file first, then rename them in order.

    A failed write leaves all previous files untouched; only a failing rename (same
    directory, so practically never) can leave the earlier targets replaced.
    """
    temps: list[Path] = []
    try:
        for target, data in files:
            temps.append(_write_temp(target.parent, data))
        for temp, (target, _) in zip(temps, files, strict=True):
            os.replace(temp, target)
    finally:
        for temp in temps:
            temp.unlink(missing_ok=True)


def _is_kept(name: str, keep: frozenset[str]) -> bool:
    """Whether file *name* is an image of an item in *keep* (temp files never are)."""
    if name.startswith(_TEMP_PREFIX):
        return False
    # The tile and thumbnail suffixes also end in the full one ("x_tile.webp" is the full
    # image of "x_tile" or the tile of "x"), so every suffix is tried.
    return any(
        name.endswith(suffix) and name[: -len(suffix)] in keep for suffix in _SUFFIXES.values()
    )


class ImageStore:
    """Image files of all inventories; stateless apart from the hass handle."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def directory(self) -> Path:
        return Path(self._hass.config.path(DOMAIN, "images"))

    def lock(self, item_id: str) -> AbstractAsyncContextManager[None]:
        """Hold *item_id*'s image lock across several steps (e.g. file + database update).

        Saves and deletes take the same lock, re-entrantly for the holding task.
        """
        self.path(item_id, "full")
        return _item_lock(item_id)

    def path(self, item_id: str, size: ImageSize) -> Path:
        """File of *item_id*'s image in *size*; ValueError for ids unsafe in a file name."""
        if not _SAFE_ITEM_ID.fullmatch(item_id):
            raise ValueError(f"Unsafe item id for an image file: {item_id!r}")
        return self.directory / f"{item_id}{_SUFFIXES[size]}"

    async def async_save_bytes(self, item_id: str, data: bytes) -> str:
        """Store *data* as *item_id*'s image; returns a new version stamp.

        Raises ImageTooLargeError / ImageInvalidError before any file is touched.
        """
        self.path(item_id, "full")
        async with _item_lock(item_id):
            return await self._hass.async_add_executor_job(self._save, item_id, data)

    def _save(self, item_id: str, data: bytes) -> str:
        full, tile, thumb = encode_image(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Thumbnail last: if a later rename ever fails, the old thumbnail - the one lists
        # show - still matches the unchanged ``image`` stamp.
        _replace_all(
            [
                (self.path(item_id, "full"), full),
                (self.path(item_id, "tile"), tile),
                (self.path(item_id, "thumb"), thumb),
            ]
        )
        return f"{time.time_ns():x}{hashlib.sha256(full).hexdigest()[:8]}"

    async def async_ensure_tile(self, item_id: str) -> Path | None:
        """The tile file, built from the full image if it is missing (photos saved before
        tiles existed); None when there is no full image. Raises ImageError if the tile
        cannot be built or written."""
        tile = self.path(item_id, "tile")
        if await self._hass.async_add_executor_job(tile.is_file):
            return tile
        async with _item_lock(item_id):
            # A concurrent request or save may have written it while this one waited.
            if await self._hass.async_add_executor_job(tile.is_file):
                return tile
            build = self._hass.async_add_executor_job(self._build_tile, item_id)
            try:
                return await asyncio.shield(build)
            except asyncio.CancelledError:
                # The request was cancelled but the thread still writes the tile: keep the
                # lock until it has, so a following save cannot be overwritten by it.
                await build
                raise

    def _build_tile(self, item_id: str) -> Path | None:
        full = self.path(item_id, "full")
        if not full.is_file():
            return None
        tile = self.path(item_id, "tile")
        try:
            _replace_all([(tile, encode_tile(full.read_bytes()))])
        except (UnidentifiedImageError, OSError, ValueError) as err:
            raise ImageInvalidError(str(err)) from err
        return tile

    async def async_delete(self, item_id: str) -> None:
        async with _item_lock(item_id):
            await self.async_delete_many((item_id,))

    async def async_delete_many(self, item_ids: Iterable[str]) -> None:
        """Best effort: a file that cannot be removed is left for the startup sweep."""
        paths = [self.path(item_id, size) for item_id in item_ids for size in _SUFFIXES]
        if not paths:
            return
        try:
            await self._hass.async_add_executor_job(_unlink_all, paths)
        except OSError as err:
            _LOGGER.warning("Could not delete item image files: %s", err)

    async def async_sweep(self, keep: Collection[str]) -> int:
        """Delete every file except the images of the item ids in *keep*; returns the count."""
        return await self._hass.async_add_executor_job(self._sweep, frozenset(keep))

    def _sweep(self, keep: frozenset[str]) -> int:
        directory = self.directory
        if not directory.is_dir():
            return 0
        removed = 0
        for entry in directory.iterdir():
            if entry.is_file() and not _is_kept(entry.name, keep):
                entry.unlink(missing_ok=True)
                removed += 1
        return removed


def _unlink_all(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


async def async_sweep_orphan_images(hass: HomeAssistant, repository: InventoryRepository) -> None:
    """Startup clean-up: drop files of items that no longer exist or have no image (I9)."""
    keep = await repository.list_item_ids_with_images()
    try:
        removed = await ImageStore(hass).async_sweep(keep)
    except OSError as err:
        _LOGGER.warning("Could not clean up item images: %s", err)
        return
    if removed:
        _LOGGER.info("Removed %d orphaned item image file(s)", removed)


async def async_delete_inventory_with_images(
    hass: HomeAssistant, repository: InventoryRepository, inventory_id: str
) -> bool:
    """Delete an inventory (cascading to its items) and its items' image files."""
    item_ids = await repository.list_item_ids_with_images(inventory_id)
    deleted = await repository.delete_inventory(inventory_id)
    await ImageStore(hass).async_delete_many(item_ids)
    return deleted
