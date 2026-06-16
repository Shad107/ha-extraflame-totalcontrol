"""Register the bundled Lovelace card with Home Assistant.

Pattern adapted from Shad107/ha-pool_pump: register the JS file as a
static HTTP path AND as a Lovelace resource so the storage-mode card
picker can resolve `custom:extraflame-stove-card` via `customElements
.whenDefined(...)`. The URL embeds the file's content hash so the
browser cache busts on integration upgrade.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .const import JSMODULES, URL_BASE

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"

_HASH_CACHE: dict[str, str] = {}


def _read_content_hash(filepath: Path) -> str:
    key = str(filepath)
    if key not in _HASH_CACHE:
        try:
            _HASH_CACHE[key] = hashlib.sha256(filepath.read_bytes()).hexdigest()[:8]
        except OSError:
            _HASH_CACHE[key] = "0"
    return _HASH_CACHE[key]


class JSModuleRegistration:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.lovelace = self.hass.data.get("lovelace")

    async def async_register(self) -> None:
        await self._async_register_path()
        if not self.lovelace:
            _LOGGER.debug("Lovelace data unavailable, skipping resource registration")
            return
        mode = getattr(self.lovelace, "mode", getattr(self.lovelace, "resource_mode", "yaml"))
        if mode == "storage":
            await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, str(FRONTEND_DIR), False)]
            )
            _LOGGER.debug("Static path registered: %s -> %s", URL_BASE, FRONTEND_DIR)
        except RuntimeError:
            _LOGGER.debug("Static path already registered: %s", URL_BASE)

    async def _async_wait_for_lovelace_resources(self) -> None:
        async def _check_loaded(_now: Any) -> None:
            if self.lovelace.resources.loaded:
                await self._async_register_modules()
            else:
                _LOGGER.debug("Lovelace resources not loaded yet, retrying in 5s")
                async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(0)

    async def _async_desired_url(self, module: dict) -> str:
        path = f"{URL_BASE}/{module['filename']}"
        h = await self.hass.async_add_executor_job(
            _read_content_hash, FRONTEND_DIR / module["filename"]
        )
        return f"{path}?v={module['version']}&h={h}"

    async def _async_register_modules(self) -> None:
        existing_resources = [
            r for r in self.lovelace.resources.async_items() if r["url"].startswith(URL_BASE)
        ]
        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            desired_url = await self._async_desired_url(module)
            registered = False
            for resource in existing_resources:
                if self._strip_query(resource["url"]) == url:
                    registered = True
                    if resource["url"] != desired_url:
                        _LOGGER.info(
                            "Updating %s resource URL: %s -> %s",
                            module["name"], resource["url"], desired_url,
                        )
                        await self.lovelace.resources.async_update_item(
                            resource["id"], {"res_type": "module", "url": desired_url}
                        )
                    break
            if not registered:
                _LOGGER.info(
                    "Registering Lovelace resource: %s v%s (%s)",
                    module["name"], module["version"], desired_url,
                )
                await self.lovelace.resources.async_create_item(
                    {"res_type": "module", "url": desired_url}
                )

    @staticmethod
    def _strip_query(url: str) -> str:
        return url.split("?")[0]
