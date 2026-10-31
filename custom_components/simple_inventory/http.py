"""Authenticated HTTP endpoints for item photos (spec 2026-10-26, I5/I6).

``GET /api/simple_inventory/image/{item_id}`` serves the WebP (``?tile=1``: the tile, built
from the full image for photos saved before tiles; ``?thumb=1``: the thumbnail, which wins);
``POST`` stores the multipart field ``file``; ``DELETE`` removes the photo. Every
authenticated user may use them (admin is not required, like the services).
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from pathlib import Path

from aiohttp import BodyPartReader, web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from .const import FIELD_IMAGE
from .coordinator import SimpleInventoryCoordinator
from .data import get_coordinators, get_repository
from .storage.images import MAX_IMAGE_BYTES, ImageError, ImageStore

_LOGGER = logging.getLogger(__name__)

IMAGE_URL = "/api/simple_inventory/image/{item_id}"
# Image URLs carry the version stamp (``&v=<stamp>``), so a cached copy never goes stale.
CACHE_CONTROL = "private, max-age=31536000, immutable"
_UPLOAD_FIELD = "file"
_CHUNK_SIZE = 64 * 1024
_STATUS_BY_ERROR = {
    "item_not_found": HTTPStatus.NOT_FOUND,
    "image_invalid": HTTPStatus.BAD_REQUEST,
    "image_too_large": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
}


@callback
def async_register_image_views(hass: HomeAssistant) -> None:
    """Register the views (once per Home Assistant run; views cannot be unregistered)."""
    hass.http.register_view(ItemImageView())


class _UploadTooLarge(Exception):
    """The uploaded file exceeds MAX_IMAGE_BYTES."""


class ItemImageView(HomeAssistantView):
    """Read, replace and delete one item's photo."""

    url = IMAGE_URL
    name = "api:simple_inventory:item_image"
    requires_auth = True

    async def get(self, request: web.Request, item_id: str) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        repository = get_repository(hass)
        item = await repository.get_item_by_id(item_id) if repository else None
        if item is None or not item.get(FIELD_IMAGE):
            return self._error("image_not_found", HTTPStatus.NOT_FOUND)
        store = ImageStore(hass)
        if request.query.get("thumb") == "1":
            path = store.path(item_id, "thumb")
        elif request.query.get("tile") == "1" and (tile := await _tile(store, item_id)):
            return _image_response(tile)  # async_ensure_tile already checked the file
        else:
            path = store.path(item_id, "full")
        if not await hass.async_add_executor_job(path.is_file):
            return self._error("image_not_found", HTTPStatus.NOT_FOUND)
        return _image_response(path)

    async def post(self, request: web.Request, item_id: str) -> web.Response:
        target = await _item_coordinator(request.app[KEY_HASS], item_id)
        if target is None:
            return self._error("item_not_found", HTTPStatus.NOT_FOUND)
        coordinator, inventory_id = target
        try:
            data = await _read_upload(request)
        except _UploadTooLarge:
            return self._error("image_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except ValueError:
            data = None
        if data is None:
            return self._error("image_invalid", HTTPStatus.BAD_REQUEST)
        try:
            stamp = await coordinator.async_set_item_image(inventory_id, item_id, data)
        except ServiceValidationError as err:
            return self._service_error(err)
        return self.json({FIELD_IMAGE: stamp})

    async def delete(self, request: web.Request, item_id: str) -> web.Response:
        target = await _item_coordinator(request.app[KEY_HASS], item_id)
        if target is None:
            return self._error("item_not_found", HTTPStatus.NOT_FOUND)
        coordinator, inventory_id = target
        try:
            await coordinator.async_clear_item_image(inventory_id, item_id)
        except ServiceValidationError as err:
            return self._service_error(err)
        return self.json({FIELD_IMAGE: ""})

    def _service_error(self, err: ServiceValidationError) -> web.Response:
        key = err.translation_key or "image_invalid"
        return self._error(key, _STATUS_BY_ERROR.get(key, HTTPStatus.BAD_REQUEST))

    def _error(self, code: str, status: HTTPStatus) -> web.Response:
        return web.json_response({"code": code}, status=status)


async def _tile(store: ImageStore, item_id: str) -> Path | None:
    """The tile file (built on demand); None to fall back to the full image."""
    try:
        return await store.async_ensure_tile(item_id)
    except ImageError as err:
        _LOGGER.warning("Could not create the tile image of %s: %s", item_id, err)
        return None


def _image_response(path: Path) -> web.FileResponse:
    return web.FileResponse(
        path, headers={"Cache-Control": CACHE_CONTROL, "Content-Type": "image/webp"}
    )


async def _item_coordinator(
    hass: HomeAssistant, item_id: str
) -> tuple[SimpleInventoryCoordinator, str] | None:
    """The loaded coordinator owning *item_id* and its inventory id, or None."""
    repository = get_repository(hass)
    item = await repository.get_item_by_id(item_id) if repository else None
    if item is None:
        return None
    inventory_id = str(item["inventory_id"])
    coordinator = get_coordinators(hass).get(inventory_id)
    return None if coordinator is None else (coordinator, inventory_id)


async def _read_upload(request: web.Request) -> bytes | None:
    """Bytes of the multipart field ``file`` (None if absent), streamed with a size cap.

    Raises _UploadTooLarge past MAX_IMAGE_BYTES and ValueError for a malformed body.
    """
    if not request.content_type.startswith("multipart/"):
        return None
    reader = await request.multipart()
    while (part := await reader.next()) is not None:
        if not isinstance(part, BodyPartReader) or part.name != _UPLOAD_FIELD:
            continue
        data = bytearray()
        while chunk := await part.read_chunk(_CHUNK_SIZE):
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:
                raise _UploadTooLarge
        return bytes(data)
    return None
