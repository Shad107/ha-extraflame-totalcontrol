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

from homeassistant.helpers.storage import Store
import time as _time

from .const import (
    AGGREGATION_MODES,
    CONF_AGGREGATION_MODE,
    CONF_AUTO_DEADBAND,
    CONF_AUTO_MAX_POWER,
    CONF_AUTO_MIN_POWER,
    CONF_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PASSWORD,
    CONF_PELLET_CONSUMPTION_P1_KG_H,
    CONF_PELLET_CONSUMPTION_P2_KG_H,
    CONF_PELLET_CONSUMPTION_P3_KG_H,
    CONF_PELLET_CONSUMPTION_P4_KG_H,
    CONF_PELLET_CONSUMPTION_P5_KG_H,
    CONF_PELLET_HOPPER_CAPACITY_KG,
    CONF_POLL_INTERVAL,
    CONF_TEMP_SENSORS,
    CONF_USERNAME,
    DEFAULT_AGGREGATION_MODE,
    DEFAULT_AUTO_DEADBAND,
    DEFAULT_AUTO_MAX_POWER,
    DEFAULT_AUTO_MIN_POWER,
    DEFAULT_PELLET_CONSUMPTION_P1_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P2_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P3_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P4_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P5_KG_H,
    DEFAULT_PELLET_HOPPER_CAPACITY_KG,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    PELLET_STORE_VERSION,
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
        # Pellet level tracking - persisted state survives HA restarts.
        # Structure: {stove_id: {"remaining_kg": float, "last_ts": float}}
        self._pellet_state: dict[str, dict[str, float]] = {}
        self._pellet_store: Store = Store(
            hass, PELLET_STORE_VERSION, f"{DOMAIN}_pellet_{entry.entry_id}"
        )
        self._pellet_loaded: bool = False

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self._pellet_loaded:
                await self._async_load_pellet_state()
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
            # Integrate pellet consumption based on the just-fetched
            # power/state. Done after auto-modulation in case it changed
            # the target - we still measure the instantaneous burn rate
            # at this tick, which is correct for an integrator.
            await self._update_pellet_consumption(snapshot)
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
                            (default - stove probe is one vote among the
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

    def outdoor_temperature(self) -> float | None:
        opts = self.config_entry.options if self.config_entry else {}
        ent = opts.get(CONF_OUTDOOR_TEMP_SENSOR)
        if not ent:
            return None
        return self._read_state_value(ent)

    def indoor_outdoor_delta(self, stove_id: str) -> float | None:
        """Δ = T_aggregate_room − T_outdoor.

        Positive = it's warmer inside than outside (the normal heating
        season case). The magnitude of this delta drives heat loss
        through the building envelope: large delta → faster cooling
        when the stove modulates down. Foundation for the v0.3.0 RC
        thermal model fit.
        """
        indoor, _ = self.aggregate_room_temperature(stove_id)
        outdoor = self.outdoor_temperature()
        if indoor is None or outdoor is None:
            return None
        return round(indoor - outdoor, 1)

    # ----- pellet hopper level tracking (v0.2.6) -----

    async def _async_load_pellet_state(self) -> None:
        """Load persisted per-stove pellet state from .storage.

        The hopper level is reconstructed from the last refill timestamp
        plus the integral of burn rate since then. Stored as the running
        value so consecutive restarts don't have to replay history - we
        just keep ticking from where we left off.
        """
        data = await self._pellet_store.async_load() or {}
        stoves = data.get("stoves") or {}
        if isinstance(stoves, dict):
            for sid, st in stoves.items():
                if not isinstance(st, dict):
                    continue
                try:
                    self._pellet_state[sid] = {
                        "remaining_kg": float(st.get("remaining_kg", self.pellet_capacity_kg())),
                        "last_ts": float(st.get("last_ts", _time.time())),
                    }
                except (TypeError, ValueError):
                    continue
        self._pellet_loaded = True

    async def _async_save_pellet_state(self) -> None:
        await self._pellet_store.async_save({"stoves": self._pellet_state})

    def pellet_capacity_kg(self) -> float:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            return float(opts.get(CONF_PELLET_HOPPER_CAPACITY_KG, DEFAULT_PELLET_HOPPER_CAPACITY_KG))
        except (TypeError, ValueError):
            return DEFAULT_PELLET_HOPPER_CAPACITY_KG

    def pellet_consumption_rate_kg_h(self, power: int) -> float:
        """Return burn rate at the given power level.

        P1..P5 are pulled from the options (user-tunable per stove model).
        Values between integers fall back to linear interpolation - useful
        only for visualisation since the cloud API always reports an
        integer targetPower.
        """
        opts = self.config_entry.options if self.config_entry else {}
        rates = {
            1: float(opts.get(CONF_PELLET_CONSUMPTION_P1_KG_H, DEFAULT_PELLET_CONSUMPTION_P1_KG_H)),
            2: float(opts.get(CONF_PELLET_CONSUMPTION_P2_KG_H, DEFAULT_PELLET_CONSUMPTION_P2_KG_H)),
            3: float(opts.get(CONF_PELLET_CONSUMPTION_P3_KG_H, DEFAULT_PELLET_CONSUMPTION_P3_KG_H)),
            4: float(opts.get(CONF_PELLET_CONSUMPTION_P4_KG_H, DEFAULT_PELLET_CONSUMPTION_P4_KG_H)),
            5: float(opts.get(CONF_PELLET_CONSUMPTION_P5_KG_H, DEFAULT_PELLET_CONSUMPTION_P5_KG_H)),
        }
        if power <= 1:
            return rates[1]
        if power >= 5:
            return rates[5]
        lo = int(power)
        hi = lo + 1
        frac = power - lo
        return rates[lo] + (rates[hi] - rates[lo]) * frac

    @staticmethod
    def _instant_power_from_params(params: dict[str, Any]) -> int:
        """Determine the burn level the stove is currently at.

        The Teodora Evo doesn't pick a fractional power on its own - but
        in MODULATION it drops to P1 silently while ``targetPower`` keeps
        the user-set value. So we read ``power`` (the actual current burn
        level) instead, falling back to ``targetPower`` if it's missing.
        Returns 0 if the stove isn't burning (OFF / STAND BY / cooling),
        so the integrator pauses cleanly.
        """
        ms_p = params.get("machineState")
        if ms_p is not None and ms_p.value is not None:
            try:
                ms = int(float(ms_p.value))
            except (TypeError, ValueError):
                ms = None
            else:
                from .const import MACHINE_STATE_RUNNING
                if ms not in MACHINE_STATE_RUNNING:
                    return 0
        cur = params.get("power")
        if cur is not None and cur.value is not None:
            try:
                v = int(float(cur.value))
                if v > 0:
                    return max(1, min(5, v))
            except (TypeError, ValueError):
                pass
        tp = params.get("targetPower")
        if tp is not None and tp.value is not None:
            try:
                return max(1, min(5, int(float(tp.value))))
            except (TypeError, ValueError):
                pass
        return 0

    async def _update_pellet_consumption(self, snapshot: dict[str, Any]) -> None:
        """Subtract the kilos burned since the last tick from each hopper."""
        now = _time.time()
        capacity = self.pellet_capacity_kg()
        changed = False
        for stove_id, snap in snapshot["stoves"].items():
            params = snap.get("parameters") or {}
            st = self._pellet_state.get(stove_id)
            if st is None:
                # First time we see this stove - assume hopper full so
                # the autonomy estimate is meaningful from the start.
                # The user calibrates with the refill button afterward.
                self._pellet_state[stove_id] = {
                    "remaining_kg": capacity,
                    "last_ts": now,
                }
                changed = True
                continue
            elapsed_h = max(0.0, (now - st["last_ts"]) / 3600.0)
            power = self._instant_power_from_params(params)
            if power > 0 and elapsed_h > 0:
                rate = self.pellet_consumption_rate_kg_h(power)
                burned = rate * elapsed_h
                st["remaining_kg"] = max(0.0, st["remaining_kg"] - burned)
                changed = True
            st["last_ts"] = now
        if changed:
            await self._async_save_pellet_state()

    def pellet_remaining_kg(self, stove_id: str) -> float | None:
        st = self._pellet_state.get(stove_id)
        if st is None:
            return None
        return round(st["remaining_kg"], 2)

    def pellet_remaining_pct(self, stove_id: str) -> float | None:
        st = self._pellet_state.get(stove_id)
        if st is None:
            return None
        cap = self.pellet_capacity_kg()
        if cap <= 0:
            return None
        return round(min(100.0, max(0.0, st["remaining_kg"] / cap * 100.0)), 1)

    def pellet_autonomy_hours(self, stove_id: str) -> float | None:
        """Hours of burn left at the current power level.

        Returns ``None`` when the stove is not burning (no rate, no
        meaningful autonomy). For a "what-if at P3" forecast, dashboards
        should multiply remaining_kg by 1 / rate(target_power) themselves.
        """
        st = self._pellet_state.get(stove_id)
        if st is None or self.data is None:
            return None
        snap = self.data.get("stoves", {}).get(stove_id, {})
        params = snap.get("parameters") or {}
        power = self._instant_power_from_params(params)
        if power <= 0:
            return None
        rate = self.pellet_consumption_rate_kg_h(power)
        if rate <= 0:
            return None
        return round(st["remaining_kg"] / rate, 1)

    async def async_refill_pellet(self, stove_id: str) -> None:
        """Reset the hopper counter - user pressed the Refill button."""
        if not self._pellet_loaded:
            await self._async_load_pellet_state()
        self._pellet_state[stove_id] = {
            "remaining_kg": self.pellet_capacity_kg(),
            "last_ts": _time.time(),
        }
        await self._async_save_pellet_state()
        self.async_update_listeners()

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
