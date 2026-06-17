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
from homeassistant.const import UnitOfMass, UnitOfTemperature, UnitOfTime
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
        entities.append(ExtraflamePelletRemainingKgSensor(coordinator, stove_id))
        entities.append(ExtraflamePelletRemainingPctSensor(coordinator, stove_id))
        entities.append(ExtraflamePelletAutonomyHoursSensor(coordinator, stove_id))
        entities.append(ExtraflameDampestRoomSensor(coordinator, stove_id))
        entities.append(ExtraflameDriestRoomSensor(coordinator, stove_id))
        entities.append(ExtraflameApparentRoomTempSensor(coordinator, stove_id))
        entities.append(ExtraflameRoomDewPointSensor(coordinator, stove_id))
        entities.append(ExtraflameThermalTauSensor(coordinator, stove_id))
        entities.append(ExtraflameHeatingPowerSensor(coordinator, stove_id))
        entities.append(ExtraflameSteadyStateTempSensor(coordinator, stove_id))
        entities.append(ExtraflameTimeToSetpointSensor(coordinator, stove_id))
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
    """``power / targetPower * 100`` - bi-modal ratio backed by the manual.

    Per the Teodora Evo official manual, the stove operates in one of
    two modes selected by the "Stand By function" toggle in the stove
    settings:

    - **Stand By OFF (factory default)** - when the room reaches the
      setpoint, the stove switches to the **minimum** burn level
      (machineState 5 "MODULATION") instead of shutting off. ratio
      hovers around ``1 / targetPower * 100`` while in MODULATION, and
      jumps back to ~100 % when the room cools below the setpoint and
      the stove re-enters WORK (state 6).

    - **Stand By ON** - when the room reaches setpoint + DELTA T OFF,
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
    embedded probe - which sits close enough to the burner to read
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


class ExtraflamePelletRemainingKgSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Estimated pellet kilos left in the hopper.

    The cloud API exposes no level reading and the Teodora Evo has no
    physical level sensor, so the value is reconstructed by integrating
    burn rate (kg/h, interpolated between P1 and P5 per the datasheet)
    over time since the last user-confirmed refill. Press the matching
    Refill button when you top up the hopper to reset the counter.
    """

    _attr_has_entity_name = True
    _attr_name = "Pellet remaining"
    _attr_icon = "mdi:weight-kilogram"
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_pellet_remaining_kg"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.pellet_remaining_kg(self._stove_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "hopper_capacity_kg": self.coordinator.pellet_capacity_kg(),
        }


class ExtraflamePelletRemainingPctSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Same level as ``pellet_remaining`` but expressed as a percentage.

    Convenience for dashboards that want a 0..100 % gauge without
    knowing the configured hopper capacity.
    """

    _attr_has_entity_name = True
    _attr_name = "Pellet level"
    _attr_icon = "mdi:gauge"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_pellet_remaining_pct"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.pellet_remaining_pct(self._stove_id)


class ExtraflamePelletAutonomyHoursSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Hours of burn left at the current power level.

    Returns ``unknown`` when the stove is off, in cooldown, or in
    STAND BY - there's no meaningful instantaneous rate to project from.
    For a forecast at a chosen target power, use a template:
    ``{{ states('sensor.<stove>_pellet_remaining') | float /
         (rate_kg_h_at_target_power) }}``
    """

    _attr_has_entity_name = True
    _attr_name = "Pellet autonomy"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_pellet_autonomy_hours"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.pellet_autonomy_hours(self._stove_id)


class ExtraflameDampestRoomSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Highest relative humidity among the selected humidity sensors.

    The state is the RH value (so it plots well next to the aggregate).
    The ``entity_id`` attribute names the room that's wettest, which is
    typically a bathroom right after a shower or a back bedroom whose
    cold wall is the first place mould will appear. Watch this over the
    heating season to spot problem rooms before the symptom does.
    """

    _attr_has_entity_name = True
    _attr_name = "Dampest room"
    _attr_icon = "mdi:water-alert"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_dampest_room"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        _ent, v = self.coordinator.dampest_room()
        return v

    @property
    def extra_state_attributes(self) -> dict:
        ent, _v = self.coordinator.dampest_room()
        return {"entity_id": ent}


class ExtraflameDriestRoomSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Lowest relative humidity among the selected humidity sensors.

    Pellet stoves dry out the air around them - this points at the room
    that's tipping below the comfort range first, the one where you'd
    park a humidifier or close a door.
    """

    _attr_has_entity_name = True
    _attr_name = "Driest room"
    _attr_icon = "mdi:water-off"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_driest_room"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        _ent, v = self.coordinator.driest_room()
        return v

    @property
    def extra_state_attributes(self) -> dict:
        ent, _v = self.coordinator.driest_room()
        return {"entity_id": ent}


class ExtraflameApparentRoomTempSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Steadman apparent room temperature, no-wind indoor variant.

    Folds aggregate humidity into aggregate temperature. Captures the
    "feels colder than the thermometer says" sensation when winter
    pellet stoves drive RH below 30%: at T=20 deg C, RH=20% drops the
    apparent temperature to ~17.5 deg C. Pair with the dew point
    sensor for the cold-wall side of "froid humide".
    """

    _attr_has_entity_name = True
    _attr_name = "Apparent room temperature"
    _attr_icon = "mdi:thermometer-water"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_apparent_room_temp"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.apparent_room_temperature(self._stove_id)


class ExtraflameRoomDewPointSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Dew point of the aggregate room, plus a per-room breakdown.

    The "humid cold" early warning. When dew point rises within a few
    degrees of a cold wall's surface temperature, water condenses and
    that wall starts to feel both cold and wet. Watch the per-room
    breakdown over winter to spot the rooms heading toward mould before
    a stain appears.
    """

    _attr_has_entity_name = True
    _attr_name = "Aggregate dew point"
    _attr_icon = "mdi:water-thermometer"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_aggregate_dew_point"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        v, _ = self.coordinator.room_dew_point(self._stove_id)
        return v

    @property
    def extra_state_attributes(self) -> dict:
        _v, breakdown = self.coordinator.room_dew_point(self._stove_id)
        return {"rooms": breakdown}


class ExtraflameThermalTauSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Time constant of the home's first-order thermal RC model.

    Big tau (15+ hours) = well-insulated brick home, the stove can rest
    long stretches before the room cools. Small tau (3-5 hours) =
    leaky envelope, the stove will need to run more aggressively.
    Updated by pressing the "Learn inertia" button, which reads the
    last 14 days of HA Recorder history (filters out stove-burning
    periods) and fits the passive decay.
    """

    _attr_has_entity_name = True
    _attr_name = "Thermal time constant"
    _attr_icon = "mdi:home-thermometer"
    _attr_native_unit_of_measurement = "h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_thermal_tau_h"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.thermal_tau_h(self._stove_id)

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.thermal_fit_meta(self._stove_id)


class ExtraflameHeatingPowerSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Instantaneous thermal output of the stove in kW.

    Q = (kg/h burned at current power) * pellet PCI (kWh/kg). Drops
    to 0 in OFF / cooling / STAND BY, since the stove isn't producing
    heat then. The pellet PCI defaults to 4.8 kWh/kg (typical wood
    pellet) and is tunable in the Configure page.
    """

    _attr_has_entity_name = True
    _attr_name = "Heating power"
    _attr_icon = "mdi:fire-circle"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "kW"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_heating_power_kw"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.heating_power_kw(self._stove_id)


class ExtraflameSteadyStateTempSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Equilibrium room temperature at the current power level.

    T_eq = T_outdoor + Q*tau/C. Where the room would settle if the
    stove kept burning at the current power forever. A pragmatic
    sanity check on power choice: if T_eq is below the setpoint, no
    amount of time will reach the target with this power level - the
    user needs to bump the stove higher.
    """

    _attr_has_entity_name = True
    _attr_name = "Steady-state temperature"
    _attr_icon = "mdi:thermometer-check"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_steady_state_temperature"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.steady_state_temperature(self._stove_id)


class ExtraflameTimeToSetpointSensor(
    CoordinatorEntity[ExtraflameCoordinator], SensorEntity
):
    """Predicted minutes for the room to reach the stove's targetRoomTemp.

    Uses the exponential ramp T(t) = T_eq + (T0 - T_eq) * exp(-t/tau).
    Returns 0 when the room is already at or above the setpoint, and
    is ``unknown`` when the chosen power level can't physically reach
    the setpoint (T_eq < T_target) - dashboards should render that as
    "out of reach, raise the power".
    """

    _attr_has_entity_name = True
    _attr_name = "Time to setpoint"
    _attr_icon = "mdi:timer-cog"
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_time_to_setpoint_min"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.time_to_setpoint_minutes(self._stove_id)


