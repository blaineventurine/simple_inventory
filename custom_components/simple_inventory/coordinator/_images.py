"""Item photo operations (spec 2026-10-26): every source ends in async_set_item_image."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components import media_source
from homeassistant.components.image_upload.const import DOMAIN as IMAGE_UPLOAD_DOMAIN
from homeassistant.components.image_upload.const import FOLDER_IMAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from ..const import DOMAIN, FIELD_IMAGE, FIELD_NAME
from ..entries import inventory_display_name
from ..providers.lookup import async_lookup_barcode_all_providers
from ..storage.images import MAX_IMAGE_BYTES, ImageInvalidError, ImageTooLargeError
from ._protocol import _CoordinatorProtocol

_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=10)
_DOWNLOAD_SCHEMES = frozenset({"http", "https"})
_CHUNK_SIZE = 64 * 1024
# image_upload names each upload folder secrets.token_hex(16) and stores the file as "original".
_IMAGE_UPLOAD_ID = re.compile(
    rf"{re.escape(media_source.URI_SCHEME)}{IMAGE_UPLOAD_DOMAIN}/([0-9a-f]{{32}})"
)


class _DownloadError(Exception):
    """The product photo could not be fetched."""


class _ImagesMixin(_CoordinatorProtocol):
    """Set and clear item photos; each change goes through the item-updated path."""

    async def async_resolve_item(
        self, inventory_id: str, name: str | None, barcode: str | None
    ) -> dict[str, Any]:
        """The item named *name* (or carrying *barcode*); raises ``item_not_found``."""
        await self.async_initialize()
        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        item = await self.repository.get_item_by_name(inventory_id, resolved_name)
        if item is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": resolved_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )
        return item

    async def async_set_item_image(self, inventory_id: str, item_id: str, data: bytes) -> str:
        """Store *data* as the item's photo and return the new ``image`` stamp.

        Raises ServiceValidationError ``item_not_found``, ``image_too_large`` or
        ``image_invalid``; the previous photo is kept on any error.
        """
        await self.async_initialize()
        await self._image_item(inventory_id, item_id)
        # Files and stamp change together: a concurrent clear cannot run in between.
        async with self.images.lock(item_id):
            try:
                stamp = await self.images.async_save_bytes(item_id, data)
            except ImageTooLargeError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="image_too_large"
                ) from err
            except ImageInvalidError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="image_invalid"
                ) from err
            if not await self.repository.update_item(item_id, {FIELD_IMAGE: stamp}):
                # The item was removed while its photo was being processed.
                await self.images.async_delete(item_id)
                raise self._image_item_not_found(inventory_id, item_id)
        await self._after_change(inventory_id)
        return stamp

    async def async_set_item_image_from_barcode(
        self, inventory_id: str, item_id: str, lookup_barcode: str | None = None
    ) -> str:
        """Use the product photo the barcode lookup returns (spec I7).

        *lookup_barcode* must be one of the item's barcodes (default: its first one). Only
        the lookup's ``image_url`` is fetched, so no caller-supplied URL is ever requested.
        """
        await self.async_initialize()
        item = await self._image_item(inventory_id, item_id)
        name = str(item[FIELD_NAME])
        barcodes = await self.repository.list_item_barcodes(item_id)
        barcode = (lookup_barcode or "").strip()
        if barcode and barcode not in barcodes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="barcode_not_on_item",
                translation_placeholders={"barcode": barcode, "name": name},
            )
        if not barcode and barcodes:
            barcode = barcodes[0]
        image_url = await _async_product_image_url(self.hass, barcode) if barcode else None
        if not image_url:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="image_not_found",
                translation_placeholders={"name": name},
            )
        try:
            data = await _async_download(self.hass, image_url)
        except ImageTooLargeError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="image_too_large"
            ) from err
        except _DownloadError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="image_download_failed",
                translation_placeholders={"name": name},
            ) from err
        return await self.async_set_item_image(inventory_id, item_id, data)

    async def async_set_item_image_from_media(
        self, inventory_id: str, item_id: str, media_content_id: str
    ) -> str:
        """Copy a file from Home Assistant's local media folders or image uploads (spec I8)."""
        await self.async_initialize()
        await self._image_item(inventory_id, item_id)
        data = await _async_read_local_media(self.hass, media_content_id)
        if data is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_source",
                translation_placeholders={"media_content_id": media_content_id},
            )
        return await self.async_set_item_image(inventory_id, item_id, data)

    async def async_clear_item_image(self, inventory_id: str, item_id: str) -> None:
        """Remove the item's photo (idempotent)."""
        await self.async_initialize()
        async with self.images.lock(item_id):
            # Read the stamp under the lock, so a set that finished meanwhile is cleared too.
            item = await self._image_item(inventory_id, item_id)
            await self.images.async_delete(item_id)
            changed = bool(item.get(FIELD_IMAGE))
            if changed:
                await self.repository.update_item(item_id, {FIELD_IMAGE: ""})
        if changed:
            await self._after_change(inventory_id)

    async def _image_item(self, inventory_id: str, item_id: str) -> dict[str, Any]:
        item = await self.repository.get_item_by_id(item_id)
        if item is None or item["inventory_id"] != inventory_id:
            raise self._image_item_not_found(inventory_id, item_id)
        return item

    def _image_item_not_found(self, inventory_id: str, item_id: str) -> ServiceValidationError:
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_not_found",
            translation_placeholders={
                "name": item_id,
                "inventory": inventory_display_name(self.hass, inventory_id),
            },
        )


async def _async_product_image_url(hass: HomeAssistant, barcode: str) -> str | None:
    """``image_url`` of the first configured provider that has one for *barcode*."""
    for result in await async_lookup_barcode_all_providers(hass, barcode):
        product = result.get("product")
        image_url = product.get("image_url", "").strip() if result["found"] and product else ""
        if image_url:
            return image_url
    return None


async def _async_download(hass: HomeAssistant, url: str) -> bytes:
    """GET an http(s) *url*: at most MAX_IMAGE_BYTES within 10 seconds.

    Raises ImageTooLargeError past the size cap and _DownloadError for anything else.
    """
    try:
        scheme = URL(url).scheme
    except ValueError as err:
        raise _DownloadError(url) from err
    if scheme not in _DOWNLOAD_SCHEMES:
        raise _DownloadError(f"unsupported scheme {scheme!r}")
    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ImageTooLargeError(url)
            return bytes(data)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise _DownloadError(url) from err


async def _async_read_local_media(hass: HomeAssistant, media_content_id: str) -> bytes | None:
    """Bytes (capped at MAX_IMAGE_BYTES + 1) of a local media file or image upload, else None."""
    if upload := _IMAGE_UPLOAD_ID.fullmatch(media_content_id):
        image_dir = Path(hass.config.path(FOLDER_IMAGE))
        original = image_dir / upload.group(1) / "original"
        return await hass.async_add_executor_job(_read_media_file, original, [image_dir])
    if not media_source.is_media_source_id(media_content_id):
        return None
    try:
        play = await media_source.async_resolve_media(hass, media_content_id, None)
    except (HomeAssistantError, ValueError, AssertionError):
        # LocalSource asserts that the file has a guessable MIME type.
        return None
    if play.path is None:
        return None
    media_dirs = [Path(directory) for directory in hass.config.media_dirs.values()]
    return await hass.async_add_executor_job(_read_media_file, play.path, media_dirs)


def _read_media_file(path: Path, media_dirs: list[Path]) -> bytes | None:
    """Read *path* only if it is a regular file inside one of *media_dirs* (symlinks resolved)."""
    resolved = path.resolve()
    roots = [directory.resolve() for directory in media_dirs]
    if not resolved.is_file() or not any(resolved.is_relative_to(root) for root in roots):
        return None
    with resolved.open("rb") as handle:
        return handle.read(MAX_IMAGE_BYTES + 1)
