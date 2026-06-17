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
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import math
import time as _time
from datetime import timedelta as _timedelta

from .const import (
    AGGREGATION_MODES,
    CONF_AGGREGATION_MODE,
    CONF_AUTO_DEADBAND,
    CONF_AUTO_MAX_POWER,
    CONF_AUTO_MIN_POWER,
    CONF_HUMIDITY_COMFORT_HIGH_PCT,
    CONF_HUMIDITY_COMFORT_LOW_PCT,
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
    CONF_COLD_SNAP_THRESHOLD_C,
    CONF_HOME_HEAT_CAPACITY_MJ_PER_K,
    CONF_PELLET_PCI_KWH_KG,
    CONF_PREHEAT_TARGET_C,
    CONF_WEATHER_ENTITY,
    DEFAULT_AUTO_MIN_POWER,
    DEFAULT_COLD_SNAP_THRESHOLD_C,
    DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K,
    DEFAULT_PREHEAT_TARGET_C,
    DEFAULT_HUMIDITY_COMFORT_HIGH_PCT,
    DEFAULT_HUMIDITY_COMFORT_LOW_PCT,
    DEFAULT_PELLET_CONSUMPTION_P1_KG_H,
    FORECAST_CACHE_SECONDS,
    DEFAULT_PELLET_PCI_KWH_KG,
    DEFAULT_PELLET_CONSUMPTION_P2_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P3_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P4_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P5_KG_H,
    DEFAULT_PELLET_HOPPER_CAPACITY_KG,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    PELLET_STORE_VERSION,
    THERMAL_COOLDOWN_AFTER_STOVE_S,
    THERMAL_LEARN_DAYS,
    THERMAL_LEARN_STATS_DAYS,
    THERMAL_MIN_SAMPLES,
    THERMAL_RESAMPLE_SECONDS,
    THERMAL_STORE_VERSION,
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
        # Thermal RC model fit (per-stove tau in hours + meta).
        # Structure: {stove_id: {"tau_h": float, "samples": int,
        #                        "last_fit_ts": float, "rmse": float}}
        self._thermal_state: dict[str, dict[str, Any]] = {}
        self._thermal_store: Store = Store(
            hass, THERMAL_STORE_VERSION, f"{DOMAIN}_thermal_{entry.entry_id}"
        )
        self._thermal_loaded: bool = False
        # Forecast cache - the weather.get_forecasts service call is
        # expensive and Meteo-France only updates hourly, so we refresh
        # at most every FORECAST_CACHE_SECONDS.
        self._forecast: list[dict[str, Any]] = []
        self._forecast_fetched_ts: float = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self._pellet_loaded:
                await self._async_load_pellet_state()
            if not self._thermal_loaded:
                await self._async_load_thermal_state()
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
            # Refresh weather forecast lazily (~30min cadence).
            await self._async_refresh_forecast_if_stale()
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

    # ----- per-room humidity scoring (v0.2.7) -----
    #
    # Reuses the same picker as aggregate_room_humidity. The aggregate
    # tells you the global vibe, these tell you *which room* is the
    # source of the problem. Useful in winter when the stove dries out
    # the salon while a back bedroom slides into mould territory.

    def _humidity_bounds(self) -> tuple[float, float]:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            lo = float(opts.get(CONF_HUMIDITY_COMFORT_LOW_PCT, DEFAULT_HUMIDITY_COMFORT_LOW_PCT))
        except (TypeError, ValueError):
            lo = DEFAULT_HUMIDITY_COMFORT_LOW_PCT
        try:
            hi = float(opts.get(CONF_HUMIDITY_COMFORT_HIGH_PCT, DEFAULT_HUMIDITY_COMFORT_HIGH_PCT))
        except (TypeError, ValueError):
            hi = DEFAULT_HUMIDITY_COMFORT_HIGH_PCT
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def _humidity_readings(self) -> dict[str, float]:
        readings: dict[str, float] = {}
        for ent in self._selected_humidity_sensors():
            v = self._read_state_value(ent)
            if v is not None:
                readings[ent] = v
        return readings

    def dampest_room(self) -> tuple[str | None, float | None]:
        readings = self._humidity_readings()
        if not readings:
            return None, None
        ent = max(readings, key=lambda k: readings[k])
        return ent, round(readings[ent], 1)

    def driest_room(self) -> tuple[str | None, float | None]:
        readings = self._humidity_readings()
        if not readings:
            return None, None
        ent = min(readings, key=lambda k: readings[k])
        return ent, round(readings[ent], 1)

    def humidity_alert(self) -> tuple[bool, list[dict[str, Any]]]:
        """Return (any_room_out_of_comfort, list_of_offenders).

        Each offender is ``{"entity_id": ..., "value": ..., "side": "low"|"high"}``
        so dashboards can show which room is too dry / too damp without
        having to compare against the bounds themselves.
        """
        lo, hi = self._humidity_bounds()
        offenders: list[dict[str, Any]] = []
        for ent, v in self._humidity_readings().items():
            if v < lo:
                offenders.append({"entity_id": ent, "value": v, "side": "low"})
            elif v > hi:
                offenders.append({"entity_id": ent, "value": v, "side": "high"})
        return bool(offenders), offenders

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

    # ----- humidity-corrected comfort (v0.3.0) -----
    #
    # The aggregate room temperature tells you the air temperature; on
    # its own it lies about how the room *feels*. Two cases where the
    # user reports "il fait froid" but the thermometer says 20 deg C:
    #
    # 1. Low RH (winter pellet stove drying the salon): below ~30% RH
    #    skin evaporation accelerates -> the body cools faster than the
    #    air should warrant. Feels 1-2 deg colder.
    #
    # 2. High RH + cold walls (old French homes, "froid humide"): the
    #    air is at 20 deg C but the radiant temperature of the walls is
    #    much lower. Operative temperature drops accordingly. The dew
    #    point is the right proxy here - when dew point is close to the
    #    wall temperature, water condenses, the walls get cold and damp.
    #
    # We don't measure wall temperature, so we expose:
    # - apparent room temperature: Steadman-style formula folding RH
    #   into the air temperature (captures case 1 and the wet-skin side
    #   of case 2)
    # - room dew point: the "humid cold" early warning that walls below
    #   this temperature will start to condense

    @staticmethod
    def _saturation_vapor_pressure_hpa(t_c: float) -> float:
        """Magnus formula. Returns saturation pressure in hPa (mbar)."""
        return 6.105 * math.exp(17.27 * t_c / (237.7 + t_c))

    @staticmethod
    def _apparent_temp_c(t_c: float, rh_pct: float) -> float:
        """Australian BOM apparent temperature, no-wind indoor variant.

        AT = T + 0.33 * e - 4
        where e = (RH/100) * saturation pressure(T)

        Dry air at 20 deg C, RH=20% -> AT ~ 17.5 deg C (feels cold)
        Humid air at 20 deg C, RH=80% -> AT ~ 22 deg C (feels warm)
        Cold + damp at 16 deg C, RH=80% -> AT ~ 16.8 deg C (close to
            air; the brutal "froid humide" sensation comes from the
            cold walls, captured separately by dew_point > wall_temp)
        """
        e = (rh_pct / 100.0) * ExtraflameCoordinator._saturation_vapor_pressure_hpa(t_c)
        return t_c + 0.33 * e - 4.0

    @staticmethod
    def _dew_point_c(t_c: float, rh_pct: float) -> float:
        """Magnus formula inversion. Dew point in deg C."""
        a, b = 17.27, 237.7
        rh = max(1.0, min(100.0, rh_pct))
        alpha = a * t_c / (b + t_c) + math.log(rh / 100.0)
        return b * alpha / (a - alpha)

    def apparent_room_temperature(self, stove_id: str) -> float | None:
        t, _ = self.aggregate_room_temperature(stove_id)
        rh, _ = self.aggregate_room_humidity(stove_id)
        if t is None or rh is None:
            return None
        return round(self._apparent_temp_c(t, rh), 1)

    def room_dew_point(self, stove_id: str) -> tuple[float | None, dict[str, float | None]]:
        """Dew point of the aggregate, plus a per-room breakdown.

        Per-room dew points need both a temperature and humidity sensor
        for the same room. We pair by stripping the trailing
        '_temperature' / '_humidite' suffix and matching the rest of
        the entity_id (Tado pattern: thermostat_salon_temperature +
        thermostat_salon_humidite). Anything that can't be paired is
        omitted from the breakdown but still folded into the aggregate.
        """
        t_agg, _ = self.aggregate_room_temperature(stove_id)
        rh_agg, _ = self.aggregate_room_humidity(stove_id)
        agg = round(self._dew_point_c(t_agg, rh_agg), 1) if (t_agg is not None and rh_agg is not None) else None

        breakdown: dict[str, float | None] = {}
        temps: dict[str, float] = {}
        for ent in self._selected_temp_sensors():
            v = self._read_state_value(ent)
            if v is not None:
                temps[ent] = v
        for ent in self._selected_humidity_sensors():
            rh = self._read_state_value(ent)
            if rh is None:
                continue
            # Try to find a matching temperature sensor by stripping
            # the humidity suffix and looking for a temperature variant.
            matched_t = None
            for suffix in ("_humidite", "_humidity", "_humidity_pct"):
                if ent.endswith(suffix):
                    stem = ent[: -len(suffix)]
                    for t_ent, t_v in temps.items():
                        if t_ent.startswith(stem):
                            matched_t = t_v
                            break
                    if matched_t is not None:
                        break
            if matched_t is None:
                continue
            breakdown[ent] = round(self._dew_point_c(matched_t, rh), 1)
        return agg, breakdown

    # ----- passive RC inertia learner (v0.3.0) -----

    async def _async_load_thermal_state(self) -> None:
        data = await self._thermal_store.async_load() or {}
        stoves = data.get("stoves") or {}
        if isinstance(stoves, dict):
            for sid, st in stoves.items():
                if isinstance(st, dict):
                    self._thermal_state[sid] = dict(st)
        self._thermal_loaded = True

    async def _async_save_thermal_state(self) -> None:
        await self._thermal_store.async_save({"stoves": self._thermal_state})

    def thermal_tau_h(self, stove_id: str) -> float | None:
        st = self._thermal_state.get(stove_id)
        if not st:
            return None
        v = st.get("tau_h")
        try:
            return round(float(v), 2) if v is not None else None
        except (TypeError, ValueError):
            return None

    def thermal_fit_meta(self, stove_id: str) -> dict[str, Any]:
        st = self._thermal_state.get(stove_id) or {}
        return {
            "samples": st.get("samples"),
            "rmse": st.get("rmse"),
            "last_fit_ts": st.get("last_fit_ts"),
            "history_days": st.get("history_days"),
            "data_source": st.get("data_source"),
            "delta_range_c": st.get("delta_range_c"),
            "delta_std_c": st.get("delta_std_c"),
            "method": st.get("method"),
            "tau_h_phase": st.get("tau_h_phase"),
            "tau_h_regression": st.get("tau_h_regression"),
            "outdoor_diurnal_amp_c": st.get("outdoor_diurnal_amp_c"),
            "indoor_diurnal_amp_c": st.get("indoor_diurnal_amp_c"),
            "phase_lag_h": st.get("phase_lag_h"),
            "low_confidence": st.get("low_confidence"),
            "per_room": st.get("per_room") or {},
        }

    def per_room_tau(self, stove_id: str) -> dict[str, dict[str, Any]]:
        st = self._thermal_state.get(stove_id) or {}
        return st.get("per_room") or {}

    def best_insulated_room(self, stove_id: str) -> tuple[str | None, float | None]:
        """Pick the room with the highest tau.

        Tau is biased upward by residual heating, but the RELATIVE
        ranking between rooms still tells you which holds heat best
        and which leaks first - which is what the user actually cares
        about for insulation upgrades. We don't filter on
        low_confidence here, so the ranking is always available.
        """
        rooms = self.per_room_tau(stove_id)
        valid = {e: m["tau_h"] for e, m in rooms.items() if m.get("tau_h") is not None}
        if not valid:
            return None, None
        ent = max(valid, key=lambda k: valid[k])
        return ent, round(valid[ent], 2)

    def worst_insulated_room(self, stove_id: str) -> tuple[str | None, float | None]:
        rooms = self.per_room_tau(stove_id)
        valid = {e: m["tau_h"] for e, m in rooms.items() if m.get("tau_h") is not None}
        if not valid:
            return None, None
        ent = min(valid, key=lambda k: valid[k])
        return ent, round(valid[ent], 2)

    def _resolve_entity_id(self, unique_id: str) -> str | None:
        try:
            ent_reg = er.async_get(self.hass)
            return ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        except Exception:  # noqa: BLE001
            return None

    async def async_learn_inertia(self, stove_id: str) -> dict[str, Any]:
        """Fit a first-order RC model from HA Recorder history.

        Strategy:
          1. Pull last THERMAL_LEARN_DAYS of indoor aggregate temp,
             outdoor temp, and the stove machine_state label.
          2. Drop any samples while the stove was running OR within
             THERMAL_COOLDOWN_AFTER_STOVE_S afterward.
          3. Resample to a uniform THERMAL_RESAMPLE_SECONDS grid.
          4. Compute dT/dt by finite difference and fit
             dT/dt = -(T_in - T_out) / tau via least-squares slope.
          5. Persist tau plus fit metadata.

        Returns the meta dict so the caller (button press) can log it.
        """
        if not self._thermal_loaded:
            await self._async_load_thermal_state()

        # Recorder lookup needs the published entity_ids of our own
        # aggregate sensors. They might have been renamed by the user,
        # so we resolve through the entity registry by unique_id.
        agg_t_eid = self._resolve_entity_id(f"extraflame_{stove_id}_aggregate_room_temp")
        outdoor_eid = self._resolve_entity_id(f"extraflame_{stove_id}_outdoor_temperature")
        state_eid = self._resolve_entity_id(f"extraflame_{stove_id}_state_label")
        if not (agg_t_eid and outdoor_eid and state_eid):
            return {"error": "missing_aggregate_or_outdoor_or_state_entity"}

        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
        from homeassistant.components.recorder.statistics import statistics_during_period

        recorder = get_instance(self.hass)
        end = dt_util.utcnow()

        # Prefer long-term statistics: HA keeps hourly means going back
        # a year+ for sensors with state_class measurement, even after
        # detailed history has been purged (default Recorder TTL is
        # 10 days). That's how we get last winter's signal even when
        # the fit is invoked in June.
        #
        # Important: our own aggregate sensor is too young (created on
        # first install of v0.2.0) to have winter stats. We instead
        # query the USER'S underlying source sensors (Tado heads,
        # Netatmo outdoor, etc.) and recompute the aggregate per hour.
        # Those source sensors have been recording for as long as the
        # user has had them.
        stats_start = end - _timedelta(days=THERMAL_LEARN_STATS_DAYS)
        data_source = "stats_hourly"
        t_in_raw: list[tuple[float, str]] = []
        t_out_raw: list[tuple[float, str]] = []
        state_raw: list[tuple[float, str]] = []
        source_temps = self._selected_temp_sensors()
        opts = self.config_entry.options if self.config_entry else {}
        source_outdoor = opts.get(CONF_OUTDOOR_TEMP_SENSOR)
        stats_entities = set(source_temps)
        if source_outdoor:
            stats_entities.add(source_outdoor)

        if stats_entities:
            try:
                stats = await recorder.async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    stats_start,
                    end,
                    stats_entities,
                    "hour",
                    None,
                    {"mean"},
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("inertia fit: stats query failed, falling back: %s", e)
                stats = {}
        else:
            stats = {}

        def _coerce_stats(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
            out: list[tuple[float, float]] = []
            for r in rows or []:
                try:
                    ts = r["start"].timestamp() if hasattr(r["start"], "timestamp") else float(r["start"])
                    v = r.get("mean")
                    if v is None:
                        continue
                    fv = float(v)
                    if fv != fv:
                        continue
                    out.append((ts, fv))
                except Exception:  # noqa: BLE001
                    continue
            return out

        if stats:
            # Build per-hour aggregate indoor temperature by averaging
            # all source sensors that have a sample for that hour.
            per_ts: dict[float, list[float]] = {}
            for eid in source_temps:
                for ts, v in _coerce_stats(stats.get(eid, [])):
                    per_ts.setdefault(ts, []).append(v)
            t_in_raw = [
                (ts, str(sum(vs) / len(vs)))
                for ts, vs in sorted(per_ts.items())
                if vs
            ]
            if source_outdoor:
                t_out_raw = [
                    (ts, str(v)) for ts, v in _coerce_stats(stats.get(source_outdoor, []))
                ]

        if len(t_in_raw) < 50 or len(t_out_raw) < 50:
            # Fall back to the detailed history mode (14 days, 5min).
            data_source = "history_14d"
            history_start = end - _timedelta(days=THERMAL_LEARN_DAYS)
            try:
                history = await recorder.async_add_executor_job(
                    get_significant_states,
                    self.hass,
                    history_start,
                    end,
                    [agg_t_eid, outdoor_eid, state_eid],
                    None,
                    True,
                    False,
                    False,
                    False,
                    False,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("inertia fit: recorder history query failed: %s", e)
                return {"error": f"recorder_query_failed: {e}"}

            def _coerce_hist(eid: str) -> list[tuple[float, str]]:
                rows = history.get(eid) or []
                out: list[tuple[float, str]] = []
                for s in rows:
                    try:
                        out.append((s.last_updated.timestamp(), s.state))
                    except Exception:  # noqa: BLE001
                        continue
                return out

            t_in_raw = _coerce_hist(agg_t_eid)
            t_out_raw = _coerce_hist(outdoor_eid)
            state_raw = _coerce_hist(state_eid)
            start = history_start
        else:
            # Long-term-stats mode: state history not available at hourly
            # resolution, so we can't filter burning periods. Acceptable
            # tradeoff - the diurnal phase fit doesn't really care about
            # short stove sessions vs. the year-long signal.
            start = stats_start

        if not (t_in_raw and t_out_raw):
            return {"error": "empty_history"}

        # Build a "stove burning" timeline: True between any "Work" /
        # "Modulation" state up until COOLDOWN_AFTER_STOVE_S past it.
        burning_until = 0.0
        burning_ranges: list[tuple[float, float]] = []
        cur_start: float | None = None
        for ts, st in state_raw:
            if st in ("Work", "Modulation"):
                if cur_start is None:
                    cur_start = ts
                burning_until = ts + THERMAL_COOLDOWN_AFTER_STOVE_S
            else:
                if cur_start is not None:
                    burning_ranges.append((cur_start, burning_until))
                    cur_start = None
        if cur_start is not None:
            burning_ranges.append((cur_start, burning_until))

        def _is_burning(ts: float) -> bool:
            for s, e in burning_ranges:
                if s <= ts <= e:
                    return True
            return False

        # Interpolation on demand for irregular series
        def _interp(series: list[tuple[float, str]], ts: float) -> float | None:
            # Linear scan is fine - we resample at most a few thousand
            # points and Recorder rows tend to be sparse already.
            prev = None
            for sts, sval in series:
                try:
                    v = float(sval)
                except (TypeError, ValueError):
                    continue
                if v != v:
                    continue
                if sts <= ts:
                    prev = (sts, v)
                else:
                    if prev is None:
                        return v
                    p_ts, p_v = prev
                    if sts == p_ts:
                        return p_v
                    f = (ts - p_ts) / (sts - p_ts)
                    return p_v + (v - p_v) * f
            return prev[1] if prev else None

        # Resample uniformly. Grid step depends on data source: hourly
        # for the long-term-stats path, 5-min for the detailed history.
        step = 3600 if data_source == "stats_hourly" else THERMAL_RESAMPLE_SECONDS
        grid: list[tuple[float, float, float]] = []
        cur = start.timestamp()
        end_ts = end.timestamp()
        # Extra filter on long-term-stats mode: only keep night-time
        # winter samples. We don't have the stove state at hourly
        # resolution across a year, and a year-wide RC fit gets
        # polluted by solar gain (summer days) and stove burning
        # (winter evenings). Filtering to 02h-06h local time in
        # Nov..Mar eliminates both confounders: the sun is off, the
        # stove is typically off, and the indoor is in passive decay
        # towards the cold outdoor - exactly what the RC model
        # describes.
        local_tz = dt_util.DEFAULT_TIME_ZONE
        from datetime import datetime as _dt
        while cur <= end_ts:
            keep = True
            if data_source == "stats_hourly":
                local = _dt.fromtimestamp(cur, tz=local_tz)
                if not (2 <= local.hour <= 6):
                    keep = False
                elif local.month not in (11, 12, 1, 2, 3):
                    keep = False
            if keep and not _is_burning(cur):
                t_in = _interp(t_in_raw, cur)
                t_out = _interp(t_out_raw, cur)
                if t_in is not None and t_out is not None:
                    grid.append((cur, t_in, t_out))
            cur += step

        # Compute (dT/dt, delta) pairs from adjacent grid points
        pairs: list[tuple[float, float]] = []
        for i in range(1, len(grid)):
            ts_a, tin_a, tout_a = grid[i - 1]
            ts_b, tin_b, _tout_b = grid[i]
            dt = ts_b - ts_a
            if dt <= 0 or dt > step * 2:
                continue
            dTdt = (tin_b - tin_a) / dt  # deg C / second
            delta = tin_a - tout_a       # at the left edge
            pairs.append((dTdt, delta))

        if len(pairs) < THERMAL_MIN_SAMPLES:
            return {"error": f"not_enough_samples: {len(pairs)} < {THERMAL_MIN_SAMPLES}"}

        # Quality stats on delta (used by both fits + the confidence flag)
        deltas = [d for _dd, d in pairs]
        d_min, d_max = min(deltas), max(deltas)
        d_mean = sum(deltas) / len(deltas)
        d_std = math.sqrt(sum((d - d_mean) ** 2 for d in deltas) / len(deltas))

        # --- method A: phase-shift fit on the 24h diurnal component ---
        #
        # First-order RC passing T_out -> T_in attenuates and phase-shifts
        # the 24h cycle. If T_out(t) = T_out_avg + A*cos(omega*t), then
        # T_in(t) = T_out_avg + (A / sqrt(1+(omega*tau)^2)) * cos(omega*t - phi)
        # where tan(phi) = omega*tau.
        #
        # Only meaningful on contiguous data covering the whole diurnal
        # cycle - we skip it in stats_hourly mode because the 02h-06h
        # winter-night filter throws away most of the cycle.
        omega = 2.0 * math.pi / 86400.0   # rad/s, 24h period
        # Use the same uniform grid produced above
        if data_source != "stats_hourly" and len(grid) >= int(86400 * 2 / step):
            t0 = grid[0][0]
            in_centered = [tin - sum(g[1] for g in grid) / len(grid) for _ts, tin, _to in grid]
            out_centered = [tout - sum(g[2] for g in grid) / len(grid) for _ts, _ti, tout in grid]
            cos_w = [math.cos(omega * (g[0] - t0)) for g in grid]
            sin_w = [math.sin(omega * (g[0] - t0)) for g in grid]
            # DFT projection at the 24h bin
            in_re = sum(v * c for v, c in zip(in_centered, cos_w))
            in_im = sum(v * s for v, s in zip(in_centered, sin_w))
            out_re = sum(v * c for v, c in zip(out_centered, cos_w))
            out_im = sum(v * s for v, s in zip(out_centered, sin_w))
            in_amp = math.sqrt(in_re ** 2 + in_im ** 2) / len(grid) * 2.0
            out_amp = math.sqrt(out_re ** 2 + out_im ** 2) / len(grid) * 2.0
            # Phase lag: how much the indoor cycle is delayed vs outdoor
            phi_in = math.atan2(in_im, in_re)
            phi_out = math.atan2(out_im, out_re)
            phi_lag = phi_in - phi_out
            # Normalise into [-pi, pi]
            while phi_lag > math.pi:
                phi_lag -= 2 * math.pi
            while phi_lag < -math.pi:
                phi_lag += 2 * math.pi
            phase_low_signal = out_amp < 1.5  # need at least 1.5 deg C diurnal swing
            phase_non_physical = phi_lag <= 0 or phi_lag >= math.pi / 2
            if phase_low_signal or phase_non_physical:
                tau_h_phase: float | None = None
            else:
                tau_h_phase = math.tan(phi_lag) / omega / 3600.0
        else:
            in_amp = out_amp = phi_lag = 0.0
            tau_h_phase = None

        # --- method B: RC regression (the original fit, used as fallback) ---
        num = sum(d * dd for dd, d in pairs)
        den = sum(d * d for _dd, d in pairs)
        slope = num / den if den > 0 else 0.0
        tau_h_reg: float | None
        if slope >= 0 or den <= 0:
            tau_h_reg = None
        else:
            tau_h_reg = -1.0 / slope / 3600.0
        # RMSE for the regression method (in deg C/s)
        if slope < 0:
            rmse_sq = sum((dd - slope * d) ** 2 for dd, d in pairs) / len(pairs)
            rmse = math.sqrt(rmse_sq)
        else:
            rmse = None

        # --- pick the winning method ---
        # Phase wins whenever it produced a physical value, because it
        # doesn't depend on having a big DC delta between inside and
        # outside. Regression is the fallback for the rare case where
        # there's no diurnal cycle at all (sealed cellar, antarctica).
        if tau_h_phase is not None and 1.0 <= tau_h_phase <= 168.0:
            tau_h = tau_h_phase
            method = "phase_24h"
        elif tau_h_reg is not None and 1.0 <= tau_h_reg <= 168.0:
            tau_h = tau_h_reg
            method = "rc_regression"
        elif tau_h_phase is not None:
            tau_h = tau_h_phase
            method = "phase_24h"
        elif tau_h_reg is not None:
            tau_h = tau_h_reg
            method = "rc_regression"
        else:
            return {
                "error": "both_methods_failed",
                "data_source": data_source,
                "grid_size": len(grid),
                "pairs": len(pairs),
                "delta_range_c": round(d_max - d_min, 2),
                "delta_std_c": round(d_std, 2),
                "outdoor_diurnal_amp_c": round(out_amp, 2),
                "indoor_diurnal_amp_c": round(in_amp, 2),
                "phase_lag_h": round(phi_lag * 86400 / (2 * math.pi) / 3600, 2),
                "tau_h_phase": tau_h_phase,
                "tau_h_regression": tau_h_reg,
            }

        low_confidence = not (1.0 <= tau_h <= 168.0)

        # ----- per-room fits (v0.5.1) -----
        # Same RC regression as above but driven by a single source
        # temperature sensor instead of the aggregate. The output tells
        # the user which room insulates well (high tau) and which one
        # is the leaky weak spot (low tau). Only attempted in
        # stats_hourly mode - in history mode we don't have enough
        # rooms-worth of data variety.
        per_room: dict[str, dict[str, Any]] = {}
        if data_source == "stats_hourly":
            for eid in source_temps:
                room_rows = _coerce_stats(stats.get(eid, []))
                if len(room_rows) < 50:
                    continue
                room_raw = [(ts, str(v)) for ts, v in room_rows]
                # Resample with the same winter-night filter
                rgrid: list[tuple[float, float, float]] = []
                rcur = start.timestamp()
                while rcur <= end_ts:
                    local = _dt.fromtimestamp(rcur, tz=local_tz)
                    if 2 <= local.hour <= 6 and local.month in (11, 12, 1, 2, 3):
                        t_in = _interp(room_raw, rcur)
                        t_out = _interp(t_out_raw, rcur)
                        if t_in is not None and t_out is not None:
                            rgrid.append((rcur, t_in, t_out))
                    rcur += step
                # Build pairs and fit
                rpairs: list[tuple[float, float]] = []
                for i in range(1, len(rgrid)):
                    ts_a, tin_a, tout_a = rgrid[i - 1]
                    ts_b, tin_b, _ = rgrid[i]
                    rdt = ts_b - ts_a
                    if rdt <= 0 or rdt > step * 2:
                        continue
                    rpairs.append(((tin_b - tin_a) / rdt, tin_a - tout_a))
                if len(rpairs) < THERMAL_MIN_SAMPLES:
                    continue
                rnum = sum(d * dd for dd, d in rpairs)
                rden = sum(d * d for _dd, d in rpairs)
                if rden <= 0:
                    continue
                rslope = rnum / rden
                if rslope >= 0:
                    continue
                rtau_h = -1.0 / rslope / 3600.0
                rdeltas = [d for _dd, d in rpairs]
                per_room[eid] = {
                    "tau_h": round(rtau_h, 2),
                    "samples": len(rpairs),
                    "delta_range_c": round(max(rdeltas) - min(rdeltas), 2),
                    "low_confidence": not (1.0 <= rtau_h <= 168.0),
                }

        self._thermal_state[stove_id] = {
            "tau_h": round(tau_h, 3),
            "samples": len(pairs),
            "rmse": rmse,
            "last_fit_ts": _time.time(),
            "history_days": (
                THERMAL_LEARN_STATS_DAYS if data_source == "stats_hourly" else THERMAL_LEARN_DAYS
            ),
            "data_source": data_source,
            "delta_range_c": round(d_max - d_min, 2),
            "delta_std_c": round(d_std, 2),
            "method": method,
            "tau_h_phase": round(tau_h_phase, 3) if tau_h_phase is not None else None,
            "tau_h_regression": round(tau_h_reg, 3) if tau_h_reg is not None else None,
            "outdoor_diurnal_amp_c": round(out_amp, 2),
            "indoor_diurnal_amp_c": round(in_amp, 2),
            "phase_lag_h": round(phi_lag * 86400 / (2 * math.pi) / 3600, 2),
            "low_confidence": low_confidence,
            "per_room": per_room,
        }
        await self._async_save_thermal_state()
        self.async_update_listeners()
        return self.thermal_fit_meta(stove_id) | {"tau_h": tau_h, "per_room": per_room}

    # ----- thermal prediction (v0.4.0) -----
    #
    # Combines the learned tau with the stove's live heat output to
    # project two useful quantities:
    #   - steady_state_temperature : where the room would settle if the
    #     current power were maintained forever
    #   - time_to_setpoint : exponential ramp from the live room temp
    #     up to targetRoomTemp at the current power level
    # Both assume a single-zone first-order RC model, which is what we
    # fit. The accuracy is bounded by tau's confidence (still low in
    # summer); the numbers grow trustworthy as the user re-presses
    # Learn inertia through autumn/winter.

    def _pci_kwh_kg(self) -> float:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            return float(opts.get(CONF_PELLET_PCI_KWH_KG, DEFAULT_PELLET_PCI_KWH_KG))
        except (TypeError, ValueError):
            return DEFAULT_PELLET_PCI_KWH_KG

    def _home_heat_capacity_j_per_k(self) -> float:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            mj = float(opts.get(CONF_HOME_HEAT_CAPACITY_MJ_PER_K, DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K))
        except (TypeError, ValueError):
            mj = DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K
        return mj * 1_000_000.0

    def heating_power_kw(self, stove_id: str) -> float | None:
        """Instantaneous thermal output of the stove in kW.

        Q = (kg/h burned at current power) * PCI (kWh/kg). Returns 0
        when the stove isn't burning (OFF / cooling / STAND BY) and
        None when we can't read the state.
        """
        snap = (self.data or {}).get("stoves", {}).get(stove_id, {})
        params = snap.get("parameters") or {}
        if not params:
            return None
        power = self._instant_power_from_params(params)
        if power <= 0:
            return 0.0
        rate = self.pellet_consumption_rate_kg_h(power)
        return round(rate * self._pci_kwh_kg(), 2)

    def steady_state_temperature(self, stove_id: str) -> float | None:
        """T_eq = T_out + Q * tau / C.

        Where the room would settle if the stove kept burning at the
        current power level forever. Useful as a sanity check on the
        user's chosen power: if T_eq is below the setpoint, no amount
        of time will reach the target with this power.
        """
        tau_h = self.thermal_tau_h(stove_id)
        q_kw = self.heating_power_kw(stove_id)
        t_out = self.outdoor_temperature()
        if tau_h is None or q_kw is None or t_out is None:
            return None
        if q_kw <= 0:
            return round(t_out, 1)  # stove off -> room drifts toward outdoor
        c_j_per_k = self._home_heat_capacity_j_per_k()
        if c_j_per_k <= 0:
            return None
        tau_s = tau_h * 3600.0
        q_w = q_kw * 1000.0
        delta_eq = q_w * tau_s / c_j_per_k
        return round(t_out + delta_eq, 1)

    def time_to_setpoint_minutes(self, stove_id: str) -> float | None:
        """t = tau * ln((T0 - T_eq) / (T_target - T_eq)).

        Returns 0 if the room is already at or above setpoint. Returns
        None if the stove can't reach the setpoint at the current
        power (T_eq < T_target) so dashboards can render "infinity".
        """
        tau_h = self.thermal_tau_h(stove_id)
        if tau_h is None or tau_h <= 0:
            return None
        t_current, _ = self.aggregate_room_temperature(stove_id)
        t_eq = self.steady_state_temperature(stove_id)
        snap = (self.data or {}).get("stoves", {}).get(stove_id, {})
        params = snap.get("parameters") or {}
        tr = params.get("targetRoomTemp")
        if t_current is None or t_eq is None or tr is None or tr.value is None:
            return None
        try:
            t_target = float(tr.value)
        except (TypeError, ValueError):
            return None
        if t_target <= t_current:
            return 0.0
        # Need T_eq strictly above T_target to reach it.
        if t_eq <= t_target + 0.1:
            return None
        try:
            ratio = (t_current - t_eq) / (t_target - t_eq)
            if ratio <= 0:
                return None
            t_h = tau_h * math.log(ratio)
            return round(t_h * 60.0, 1)
        except (ValueError, ZeroDivisionError):
            return None

    # ----- weather anticipation (v0.5.0) -----
    #
    # Pulls hourly forecast from any weather.* entity (Meteo-France,
    # Met.no, OpenWeatherMap, ...) and combines it with the learned
    # tau + the v0.4.0 steady-state model to recommend when to start
    # the stove ahead of a cold snap. The point: pellet stoves take
    # 10-30 minutes to ignite + ramp from cold; by the time you notice
    # the room got cold, the stove can't catch up in time. Knowing the
    # forecast lets us start the stove ~tau/2 hours before the cold
    # snap so the room never actually drops.

    def _weather_entity(self) -> str | None:
        opts = self.config_entry.options if self.config_entry else {}
        v = opts.get(CONF_WEATHER_ENTITY)
        if v:
            return v
        # Auto-discover the first weather.* entity if user hasn't picked
        # one yet - convenient default for users with only one source.
        for state in self.hass.states.async_all():
            if state.entity_id.startswith("weather."):
                return state.entity_id
        return None

    def _cold_snap_threshold_c(self) -> float:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            return float(opts.get(CONF_COLD_SNAP_THRESHOLD_C, DEFAULT_COLD_SNAP_THRESHOLD_C))
        except (TypeError, ValueError):
            return DEFAULT_COLD_SNAP_THRESHOLD_C

    def _preheat_target_c(self) -> float:
        opts = self.config_entry.options if self.config_entry else {}
        try:
            return float(opts.get(CONF_PREHEAT_TARGET_C, DEFAULT_PREHEAT_TARGET_C))
        except (TypeError, ValueError):
            return DEFAULT_PREHEAT_TARGET_C

    async def _async_refresh_forecast_if_stale(self) -> None:
        now = _time.time()
        if now - self._forecast_fetched_ts < FORECAST_CACHE_SECONDS:
            return
        weather_eid = self._weather_entity()
        if not weather_eid:
            return
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_eid, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("forecast fetch failed: %s", e)
            return
        try:
            entries = (response or {}).get(weather_eid, {}).get("forecast", [])
        except AttributeError:
            entries = []
        # Normalise to (ts_utc, temp_c) - the only fields we use
        normalised: list[dict[str, Any]] = []
        for entry in entries:
            try:
                ts_raw = entry.get("datetime")
                if hasattr(ts_raw, "timestamp"):
                    ts = ts_raw.timestamp()
                else:
                    # ISO 8601 string
                    ts = dt_util.parse_datetime(str(ts_raw)).timestamp()
                t = float(entry.get("temperature"))
            except Exception:  # noqa: BLE001
                continue
            normalised.append({"ts": ts, "temperature": t})
        if normalised:
            self._forecast = normalised
            self._forecast_fetched_ts = now

    def forecast_min_temp_24h(self) -> float | None:
        if not self._forecast:
            return None
        now = _time.time()
        horizon = now + 24 * 3600
        upcoming = [e["temperature"] for e in self._forecast if now <= e["ts"] <= horizon]
        if not upcoming:
            return None
        return round(min(upcoming), 1)

    def cold_snap_in_hours(self) -> float | None:
        """Hours until the next forecast hour below the cold-snap threshold.

        Returns None when the next 48h forecast stays warm, so dashboards
        can render "no cold snap pending" cleanly.
        """
        if not self._forecast:
            return None
        threshold = self._cold_snap_threshold_c()
        now = _time.time()
        for entry in self._forecast:
            if entry["ts"] < now:
                continue
            if entry["temperature"] <= threshold:
                return round((entry["ts"] - now) / 3600.0, 1)
            if entry["ts"] > now + 48 * 3600:
                break
        return None

    def recommended_preheat_at(self, stove_id: str) -> float | None:
        """Unix timestamp at which to start the stove ahead of a cold snap.

        Lead time is tau/2 (hours) - a heuristic that balances pre-heat
        cost against catching up. Without a valid tau we return None so
        the user sees "data not ready yet" instead of a wrong number.
        """
        snap_in_h = self.cold_snap_in_hours()
        tau_h = self.thermal_tau_h(stove_id)
        if snap_in_h is None or tau_h is None or tau_h <= 0:
            return None
        # Cap lead time at 4h - beyond that we'd burn pellets for nothing
        lead_h = min(4.0, tau_h / 2.0)
        return _time.time() + (snap_in_h - lead_h) * 3600.0

    def should_preheat_now(self, stove_id: str) -> bool:
        ts = self.recommended_preheat_at(stove_id)
        if ts is None:
            return False
        # ON during a 90-minute window after the recommended time, so a
        # missed minute-tick doesn't make the flag bounce back off.
        now = _time.time()
        return ts <= now <= ts + 90 * 60

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
