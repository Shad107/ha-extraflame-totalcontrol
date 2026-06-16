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

from .const import DOMAIN
from .coordinator import ExtraflameCoordinator

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
    entities: list[ExtraflameSensor] = []
    for stove_id in coordinator.data.get("stoves", {}):
        for key, name, unit, device_class, state_class in SENSORS:
            entities.append(
                ExtraflameSensor(coordinator, stove_id, key, name, unit, device_class, state_class)
            )
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
