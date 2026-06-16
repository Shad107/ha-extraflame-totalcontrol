"""Polling coordinator that wraps the cloud client."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from extraflame_totalcontrol import (  # type: ignore
    ExtraflameAPIError,
    ExtraflameAuthError,
    ExtraflameClient,
)

from .const import (
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_USERNAME,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ExtraflameCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the cloud at a fixed interval, exposes the latest snapshot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self._client = ExtraflameClient(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            stoves = await self._client.list_stoves()
            snapshot: dict[str, Any] = {"stoves": {}}
            for s in stoves:
                params = await self._client.get_parameters(s.id)
                online = await self._client.is_online(s.id)
                snapshot["stoves"][s.id] = {
                    "stove": s,
                    "parameters": params,
                    "online": online,
                }
            return snapshot
        except ExtraflameAuthError as e:
            raise UpdateFailed(f"Authentication failed: {e}") from e
        except ExtraflameAPIError as e:
            raise UpdateFailed(f"API error: {e}") from e

    async def async_close(self) -> None:
        await self._client.close()
