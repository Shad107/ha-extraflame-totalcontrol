"""Polling coordinator that wraps the cloud client."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.helpers.device_registry import DeviceInfo, format_mac

from .api_client import (
    ExtraflameAPIError,
    ExtraflameAuthError,
    ExtraflameClient,
    Stove,
)

from .models import resolve_model

from .const import (
    CONF_AUTO_DEADBAND,
    CONF_AUTO_MAX_POWER,
    CONF_AUTO_MIN_POWER,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_USERNAME,
    DEFAULT_AUTO_DEADBAND,
    DEFAULT_AUTO_MAX_POWER,
    DEFAULT_AUTO_MIN_POWER,
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
        self.config_entry = entry
        self._client = ExtraflameClient(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
        # Registered Auto-Modulation switch instances, keyed by stove_id.
        self._auto_switches: dict[str, Any] = {}

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
            for stove_id in snapshot["stoves"]:
                sw = self._auto_switches.get(stove_id)
                if sw is not None and getattr(sw, "is_on", False):
                    await self._apply_auto_modulation_from_snapshot(stove_id, snapshot)
            return snapshot
        except ExtraflameAuthError as e:
            raise UpdateFailed(f"Authentication failed: {e}") from e
        except ExtraflameAPIError as e:
            raise UpdateFailed(f"API error: {e}") from e

    def register_auto_modulation(self, stove_id: str, switch) -> None:
        self._auto_switches[stove_id] = switch

    def unregister_auto_modulation(self, stove_id: str) -> None:
        self._auto_switches.pop(stove_id, None)

    def _auto_bounds(self) -> tuple[int, int, float]:
        opts = self.config_entry.options if self.config_entry else {}
        return (
            int(opts.get(CONF_AUTO_MIN_POWER, DEFAULT_AUTO_MIN_POWER)),
            int(opts.get(CONF_AUTO_MAX_POWER, DEFAULT_AUTO_MAX_POWER)),
            float(opts.get(CONF_AUTO_DEADBAND, DEFAULT_AUTO_DEADBAND)),
        )

    @staticmethod
    def compute_auto_power(delta: float, min_p: int, max_p: int) -> int:
        """Δ (°C) → P inside [min_p, max_p]. Simple staircase ~ 1 °C / step."""
        steps = int(max(0.0, delta))
        return max(min_p, min(max_p, min_p + steps))

    async def _apply_auto_modulation_from_snapshot(
        self, stove_id: str, snapshot: dict[str, Any]
    ) -> None:
        params = snapshot["stoves"][stove_id].get("parameters") or {}
        tr = params.get("targetRoomTemp")
        rt = params.get("roomTemp")
        tp = params.get("targetPower")
        if tr is None or rt is None or tp is None:
            return
        try:
            delta = float(tr.value) - float(rt.value)
            cur_target = int(float(tp.value))
        except (TypeError, ValueError, AttributeError):
            return
        min_p, max_p, _deadband = self._auto_bounds()
        new_target = self.compute_auto_power(delta, min_p, max_p)
        if new_target != cur_target:
            await self._client.set_power(stove_id, new_target)

    async def apply_auto_modulation(self, stove_id: str) -> None:
        if not self.data or stove_id not in self.data.get("stoves", {}):
            return
        await self._apply_auto_modulation_from_snapshot(stove_id, self.data)

    async def async_close(self) -> None:
        await self._client.close()


def stove_device_info(stove: Stove) -> DeviceInfo:
    """Build the DeviceInfo describing a stove. Used by every entity."""
    identifiers = {(DOMAIN, stove.id)}
    connections = set()
    if stove.mac_address:
        try:
            connections.add(("mac", format_mac(stove.mac_address)))
        except Exception:
            pass
    return DeviceInfo(
        identifiers=identifiers,
        connections=connections,
        manufacturer="La Nordica-Extraflame",
        model=resolve_model(stove.resource_id),
        model_id=stove.resource_id or None,
        name=stove.name or f"Extraflame {stove.id[:8]}",
        suggested_area="Salon",
    )
