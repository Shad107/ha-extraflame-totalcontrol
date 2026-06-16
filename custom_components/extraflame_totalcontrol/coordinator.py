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
    AGGREGATION_MODES,
    CONF_AGGREGATION_MODE,
    CONF_AUTO_DEADBAND,
    CONF_AUTO_MAX_POWER,
    CONF_AUTO_MIN_POWER,
    CONF_HUMIDITY_SENSORS,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_TEMP_SENSORS,
    CONF_USERNAME,
    DEFAULT_AGGREGATION_MODE,
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
        tp = params.get("targetPower")
        if tr is None or tp is None:
            return
        try:
            target_temp = float(tr.value)
            cur_target = int(float(tp.value))
        except (TypeError, ValueError, AttributeError):
            return
        # Use the multi-source aggregate as the room temperature input
        # so the auto-modulation reacts to the user's actual comfort
        # zone (Tado salon + cuisine + …) and not to the probe sitting
        # 30 cm from the burner.
        room_temp, _ = self.aggregate_room_temperature(stove_id)
        if room_temp is None:
            return
        delta = target_temp - room_temp
        min_p, max_p, _deadband = self._auto_bounds()
        new_target = self.compute_auto_power(delta, min_p, max_p)
        if new_target != cur_target:
            await self._client.set_power(stove_id, new_target)

    async def apply_auto_modulation(self, stove_id: str) -> None:
        if not self.data or stove_id not in self.data.get("stoves", {}):
            return
        await self._apply_auto_modulation_from_snapshot(stove_id, self.data)

    # ----- multi-source temperature / humidity aggregation -----

    def _read_state_value(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "unknown", "unavailable", ""):
            return None
        try:
            v = float(state.state)
        except (TypeError, ValueError):
            return None
        if v != v:  # NaN
            return None
        return v

    def _selected_temp_sensors(self) -> list[str]:
        opts = self.config_entry.options if self.config_entry else {}
        v = opts.get(CONF_TEMP_SENSORS) or []
        return list(v) if isinstance(v, (list, tuple)) else []

    def _selected_humidity_sensors(self) -> list[str]:
        opts = self.config_entry.options if self.config_entry else {}
        v = opts.get(CONF_HUMIDITY_SENSORS) or []
        return list(v) if isinstance(v, (list, tuple)) else []

    def _aggregation_mode(self) -> str:
        opts = self.config_entry.options if self.config_entry else {}
        mode = opts.get(CONF_AGGREGATION_MODE, DEFAULT_AGGREGATION_MODE)
        return mode if mode in AGGREGATION_MODES else DEFAULT_AGGREGATION_MODE

    def aggregate_room_temperature(self, stove_id: str) -> tuple[float | None, dict[str, float | None]]:
        """Return (aggregate_temp, breakdown_dict).

        The stove's own ``roomTemp`` parameter is always included as one
        of the inputs. Externally-selected temperature sensors are
        pulled from hass.states.

        ``mode``:
        - ``stove_only``  : ignore externals, return stove probe only
        - ``min``         : the coldest measurement wins (protective)
        - ``max``         : the warmest measurement wins (comfort)
        - ``weighted_avg``: equal-weight mean of all valid readings
                            (default — stove probe is one vote among the
                            external sensors)
        """
        breakdown: dict[str, float | None] = {}
        snap = (self.data or {}).get("stoves", {}).get(stove_id, {})
        params = snap.get("parameters") or {}
        stove_p = params.get("roomTemp")
        stove_v: float | None = None
        if stove_p is not None and stove_p.value is not None:
            try:
                v = float(stove_p.value)
                if v == v:
                    stove_v = v
            except (TypeError, ValueError):
                pass
        breakdown["stove"] = stove_v

        mode = self._aggregation_mode()
        if mode == "stove_only":
            return stove_v, breakdown

        for ent in self._selected_temp_sensors():
            breakdown[ent] = self._read_state_value(ent)

        readings = [v for v in breakdown.values() if v is not None]
        if not readings:
            return None, breakdown
        if mode == "min":
            return round(min(readings), 2), breakdown
        if mode == "max":
            return round(max(readings), 2), breakdown
        # weighted_avg (equal weights for v0.2.0; per-sensor weights TODO v0.2.x)
        return round(sum(readings) / len(readings), 2), breakdown

    def aggregate_room_humidity(self, stove_id: str) -> tuple[float | None, dict[str, float | None]]:
        breakdown: dict[str, float | None] = {}
        for ent in self._selected_humidity_sensors():
            breakdown[ent] = self._read_state_value(ent)
        readings = [v for v in breakdown.values() if v is not None]
        if not readings:
            return None, breakdown
        return round(sum(readings) / len(readings), 1), breakdown

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
