"""Online binary sensor per stove."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExtraflameCoordinator


SMOKE_TEMP_WARNING_C = 400.0  # red-glow risk threshold for flue pipes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for stove_id in coordinator.data.get("stoves", {}):
        entities.append(ExtraflameOnlineSensor(coordinator, stove_id))
        entities.append(ExtraflameSmokeWarning(coordinator, stove_id))
        entities.append(ExtraflameAlarm(coordinator, stove_id))
    async_add_entities(entities)


class ExtraflameOnlineSensor(CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_online"

    @property
    def is_on(self) -> bool:
        return bool(
            (self.coordinator.data or {})
            .get("stoves", {})
            .get(self._stove_id, {})
            .get("online")
        )


def _param(coordinator, stove_id, key):
    snap = (coordinator.data or {}).get("stoves", {}).get(stove_id, {})
    p = (snap.get("parameters") or {}).get(key)
    if p is None:
        return None
    v = p.value
    if isinstance(v, float) and (v != v):
        return None
    return v


class ExtraflameSmokeWarning(CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity):
    """ON when smoke (flue) temperature is at red-glow risk.

    The ``smokeTemp`` parameter is exposed by the TotalControl 2.0 cloud
    API but not surfaced by the official app. Above ~400 °C, steel and
    cast-iron flue pipes start glowing red — a fire-hazard warning sign
    well known on stove communities. Crossing this threshold typically
    means too much air, draft pulled too high, or oversized pellet
    feeding — worth investigating before the next firing.
    """

    _attr_has_entity_name = True
    _attr_name = "Smoke temperature warning"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_smoke_warning"

    @property
    def is_on(self) -> bool:
        v = _param(self.coordinator, self._stove_id, "smokeTemp")
        return v is not None and float(v) >= SMOKE_TEMP_WARNING_C


class ExtraflameAlarm(CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity):
    """ON when the stove reports an alarm code != 0."""

    _attr_has_entity_name = True
    _attr_name = "Alarm"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_alarm"

    @property
    def is_on(self) -> bool:
        v = _param(self.coordinator, self._stove_id, "alarmCode")
        return v is not None and float(v) != 0

    @property
    def extra_state_attributes(self) -> dict:
        v = _param(self.coordinator, self._stove_id, "alarmCode")
        return {"alarm_code": v}
