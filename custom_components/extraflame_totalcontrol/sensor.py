"""Sensor entities for Extraflame stoves.

Exposes the live cloud parameters as HA sensors: room/water/smoke temp,
current power, target power, alarm code, etc.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MACHINE_STATE_LABELS
from .coordinator import ExtraflameCoordinator, stove_device_info
from .models import resolve_model, RESOURCE_ID_TO_MODEL
from .visual import render_stove_svg

SENSORS: tuple[tuple[str, str, str | None, str | None, str | None], ...] = (
    # (param_key, friendly suffix, unit, device_class, state_class)
    ("roomTemp", "Room temperature", UnitOfTemperature.CELSIUS,
     SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    ("waterTemp", "Water temperature", UnitOfTemperature.CELSIUS,
     SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    ("smokeTemp", "Smoke temperature", UnitOfTemperature.CELSIUS,
     SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    ("power", "Current power", None, None, SensorStateClass.MEASUREMENT),
    ("targetPower", "Target power", None, None, None),
    ("targetRoomTemp", "Target room temperature", UnitOfTemperature.CELSIUS,
     SensorDeviceClass.TEMPERATURE, None),
    ("machineState", "Machine state", None, None, None),
    ("alarmCode", "Alarm code", None, None, None),
    ("mainFanSpeed", "Main fan speed", None, None, SensorStateClass.MEASUREMENT),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for stove_id in coordinator.data.get("stoves", {}):
        for key, name, unit, device_class, state_class in SENSORS:
            entities.append(
                ExtraflameSensor(coordinator, stove_id, key, name, unit, device_class, state_class)
            )
        entities.append(ExtraflameVisualSensor(coordinator, stove_id))
        entities.append(ExtraflameStateLabelSensor(coordinator, stove_id))
        entities.append(ExtraflameThermalDeltaSensor(coordinator, stove_id))
        entities.append(ExtraflameBurnIntensitySensor(coordinator, stove_id))
        entities.append(ExtraflameAggregateTempSensor(coordinator, stove_id))
        entities.append(ExtraflameAggregateHumiditySensor(coordinator, stove_id))
        entities.append(ExtraflameOutdoorTempSensor(coordinator, stove_id))
        entities.append(ExtraflameIndoorOutdoorDeltaSensor(coordinator, stove_id))
    async_add_entities(entities)


class ExtraflameSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ExtraflameCoordinator,
        stove_id: str,
        param_key: str,
        friendly: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._param_key = param_key
        self._attr_name = friendly
        self._attr_unique_id = f"extraflame_{stove_id}_{param_key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> Any:
        snap = (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {})
        param = (snap.get("parameters") or {}).get(self._param_key)
        if param is None:
            return None
        v = param.value
        if isinstance(v, float) and (v != v):  # NaN
            return None
        return v


class ExtraflameVisualSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Sensor whose value is the stove name and whose ``svg`` attribute
    holds an inline SVG depicting the stove. The Lovelace markdown card
    renders it via ``{{ state_attr('sensor.<stove>_visual', 'svg') }}``.
    """

    _attr_has_entity_name = True
    _attr_name = "Visual"
    _attr_icon = "mdi:stove"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_visual"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    def _snap(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {})

    def _param(self, key: str) -> Any:
        params = self._snap().get("parameters") or {}
        p = params.get(key)
        if p is None:
            return None
        v = p.value
        if isinstance(v, float) and (v != v):
            return None
        return v

    @property
    def native_value(self) -> str | None:
        s = self._snap().get("stove")
        return s.name if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stove = self._snap().get("stove")
        ms = self._param("machineState")
        target_p = self._param("targetPower")
        try:
            cur_pow = int(float(target_p)) if target_p is not None else 0
        except (TypeError, ValueError):
            cur_pow = 0
        svg = render_stove_svg(
            name=stove.name if stove else "",
            online=bool(self._snap().get("online")),
            machine_state=int(ms) if ms is not None else None,
            current_power=cur_pow,
            room_temp=self._param("roomTemp"),
            target_room_temp=self._param("targetRoomTemp"),
            smoke_temp=self._param("smokeTemp"),
        )
        rid = stove.resource_id if stove else None
        is_known_model = bool(rid and rid in RESOURCE_ID_TO_MODEL)
        return {
            "svg": svg,
            "model": resolve_model(rid) if is_known_model else None,
            "manufacturer": "La Nordica-Extraflame",
            "resource_id": rid,
            "stove_name": stove.name if stove else None,
        }


class ExtraflameStateLabelSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Human-readable state of the stove (Off / Allumage / Running / …).

    Sits next to the raw ``machine_state`` int sensor and translates it
    via :data:`MACHINE_STATE_LABELS`. Codes outside the map fall back to
    ``État N`` so the user sees the raw value while we get more samples.
    """

    _attr_has_entity_name = True
    _attr_name = "State"
    _attr_icon = "mdi:state-machine"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(MACHINE_STATE_LABELS.values())

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_state_label"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> str | None:
        params = (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {}).get("parameters") or {}
        p = params.get("machineState")
        if p is None or p.value is None:
            return None
        try:
            n = int(float(p.value))
        except (TypeError, ValueError):
            return None
        return MACHINE_STATE_LABELS.get(n, f"État {n}")


def _param_float(coord, stove_id, key) -> float | None:
    params = (coord.data or {}).get("stoves", {}).get(stove_id, {}).get("parameters") or {}
    p = params.get(key)
    if p is None or p.value is None:
        return None
    try:
        v = float(p.value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


class ExtraflameThermalDeltaSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Δ = targetRoomTemp − roomTemp.

    Drives the stove's WORK ↔ MODULATION ↔ STAND BY transitions per
    the Teodora Evo manual:

    - Δ > 0 (room below setpoint)      → WORK (burning at targetPower)
    - Δ ≤ 0 with Stand By OFF (factory)→ MODULATION (burning at minimum)
    - Δ < −(DELTA T OFF), Stand By ON → STAND BY (off, awaiting cooldown)

    The hysteresis (DELTA T OFF) is configurable in the stove's user
    menu but not exposed by the cloud API. Observe this sensor over a
    heating session against ``state`` transitions to back it out.
    """

    _attr_has_entity_name = True
    _attr_name = "Thermal delta"
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_thermal_delta"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        target = _param_float(self.coordinator, self._stove_id, "targetRoomTemp")
        room = _param_float(self.coordinator, self._stove_id, "roomTemp")
        if target is None or room is None:
            return None
        return round(target - room, 1)


class ExtraflameBurnIntensitySensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """``power / targetPower * 100`` — bi-modal ratio backed by the manual.

    Per the Teodora Evo official manual, the stove operates in one of
    two modes selected by the "Stand By function" toggle in the stove
    settings:

    - **Stand By OFF (factory default)** — when the room reaches the
      setpoint, the stove switches to the **minimum** burn level
      (machineState 5 "MODULATION") instead of shutting off. ratio
      hovers around ``1 / targetPower * 100`` while in MODULATION, and
      jumps back to ~100 % when the room cools below the setpoint and
      the stove re-enters WORK (state 6).

    - **Stand By ON** — when the room reaches setpoint + DELTA T OFF,
      the stove shuts off entirely (machineState 9 "STAND BY").
      ratio drops to 0 % until the room cools enough to re-ignite.

    The cloud API doesn't expose the Stand By flag, so this sensor
    reveals which mode is active by observation alone. Pair with
    ``thermal_delta`` to see the room/setpoint gap that drives the
    next transition.
    """

    _attr_has_entity_name = True
    _attr_name = "Burn intensity"
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_burn_intensity"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        cur = _param_float(self.coordinator, self._stove_id, "power")
        cap = _param_float(self.coordinator, self._stove_id, "targetPower")
        if cur is None or cap is None or cap <= 0:
            return None
        return round(min(100.0, max(0.0, cur / cap * 100.0)), 0)


class ExtraflameAggregateTempSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Multi-source room temperature seen by the stove.

    Combines the stove's built-in probe (``roomTemp``) with any external
    HA temperature sensors the user picked from the Options page. The
    auto-modulation algorithm uses this value instead of the lone
    embedded probe — which sits close enough to the burner to read
    biased upward.

    The ``sources`` attribute reports each input value so the dashboard
    can show "Salon 21.3 °C · Cuisine 20.1 °C · Poêle 22.7 °C".
    """

    _attr_has_entity_name = True
    _attr_name = "Aggregate room temperature"
    _attr_icon = "mdi:thermometer-lines"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_aggregate_room_temp"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        v, _ = self.coordinator.aggregate_room_temperature(self._stove_id)
        return v

    @property
    def extra_state_attributes(self) -> dict:
        v, breakdown = self.coordinator.aggregate_room_temperature(self._stove_id)
        mode = self.coordinator._aggregation_mode()
        return {
            "mode": mode,
            "sources": breakdown,
            "input_count": sum(1 for x in breakdown.values() if x is not None),
        }


class ExtraflameAggregateHumiditySensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Average humidity across the externally-selected humidity sensors.

    Not used to drive the stove (no humidity input on the cloud API)
    but exposed for dashboards and for future automations (e.g. boost
    when the room is dry, eco when comfort RH is reached).
    """

    _attr_has_entity_name = True
    _attr_name = "Aggregate room humidity"
    _attr_icon = "mdi:water-percent"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_aggregate_room_humidity"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        v, _ = self.coordinator.aggregate_room_humidity(self._stove_id)
        return v

    @property
    def extra_state_attributes(self) -> dict:
        v, breakdown = self.coordinator.aggregate_room_humidity(self._stove_id)
        return {
            "sources": breakdown,
            "input_count": sum(1 for x in breakdown.values() if x is not None),
        }


class ExtraflameOutdoorTempSensor(CoordinatorEntity[ExtraflameCoordinator], SensorEntity):
    """Mirror of the user-picked outdoor temperature sensor.

    Exposed under the stove device for two reasons:
    - keeps the thermal context on the same Lovelace card
    - the v0.3.0 inertia learner reads it via a stable entity_id
      regardless of the underlying source (Netatmo today, Tado outdoor
      tomorrow, Météo France as fallback)
    """

    _attr_has_entity_name = True
    _attr_name = "Outdoor temperature"
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_outdoor_temperature"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.outdoor_temperature()


class ExtraflameIndoorOutdoorDeltaSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Δ = aggregate indoor temp − outdoor temp.

    The thermodynamic driver of heat loss through the building
    envelope. Used in v0.3.0 to fit the first-order RC model
    (dT_indoor/dt = −Δ/τ + heating_input/C), and in v0.4.0 to predict
    when to start the stove ahead of a cold snap.

    Positive in winter, can go negative on warm sunny days when the
    sun warms the outdoor sensor faster than the room.
    """

    _attr_has_entity_name = True
    _attr_name = "Indoor-outdoor delta"
    _attr_icon = "mdi:thermometer-minus"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_indoor_outdoor_delta"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.indoor_outdoor_delta(self._stove_id)


