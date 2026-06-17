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

from .const import (
    DOMAIN,
    PELLET_CRITICAL_WARNING_PCT,
    PELLET_LOW_WARNING_PCT,
)
from .coordinator import ExtraflameCoordinator, stove_device_info


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
        entities.append(ExtraflamePelletLowWarning(coordinator, stove_id))
        entities.append(ExtraflamePelletCriticalWarning(coordinator, stove_id))
        entities.append(ExtraflameHumidityAlert(coordinator, stove_id))
        entities.append(ExtraflameShouldPreheatNow(coordinator, stove_id))
    async_add_entities(entities)


class ExtraflameOnlineSensor(CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
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
    cast-iron flue pipes start glowing red - a fire-hazard warning sign
    well known on stove communities. Crossing this threshold typically
    means too much air, draft pulled too high, or oversized pellet
    feeding - worth investigating before the next firing.
    """

    _attr_has_entity_name = True
    _attr_name = "Smoke temperature warning"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
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
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_alarm"

    @property
    def is_on(self) -> bool:
        v = _param(self.coordinator, self._stove_id, "alarmCode")
        return v is not None and float(v) != 0

    @property
    def extra_state_attributes(self) -> dict:
        v = _param(self.coordinator, self._stove_id, "alarmCode")
        return {"alarm_code": v}


class ExtraflamePelletLowWarning(
    CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity
):
    """ON when the estimated hopper level drops below the low threshold."""

    _attr_has_entity_name = True
    _attr_name = "Pellet low"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:fuel"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_pellet_low_warning"

    @property
    def is_on(self) -> bool:
        pct = self.coordinator.pellet_remaining_pct(self._stove_id)
        return pct is not None and pct <= PELLET_LOW_WARNING_PCT


class ExtraflamePelletCriticalWarning(
    CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity
):
    """ON when the hopper is near empty - refill before the next session."""

    _attr_has_entity_name = True
    _attr_name = "Pellet critical"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:fuel-cell"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_pellet_critical_warning"

    @property
    def is_on(self) -> bool:
        pct = self.coordinator.pellet_remaining_pct(self._stove_id)
        return pct is not None and pct <= PELLET_CRITICAL_WARNING_PCT


class ExtraflameHumidityAlert(
    CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity
):
    """ON when any selected humidity sensor is outside the comfort band.

    The ``offenders`` attribute lists each room that's too dry or too
    damp, so a single notification action can name the rooms instead of
    a vague "humidity alert". Side is "low" (dry, < comfort floor) or
    "high" (damp, > comfort ceiling); bounds are user-tunable from the
    Configure page.
    """

    _attr_has_entity_name = True
    _attr_name = "Humidity alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-percent-alert"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_humidity_alert"

    @property
    def is_on(self) -> bool:
        on, _ = self.coordinator.humidity_alert()
        return on

    @property
    def extra_state_attributes(self) -> dict:
        _on, offenders = self.coordinator.humidity_alert()
        lo, hi = self.coordinator._humidity_bounds()
        return {
            "comfort_low_pct": lo,
            "comfort_high_pct": hi,
            "offenders": offenders,
        }


class ExtraflameShouldPreheatNow(
    CoordinatorEntity[ExtraflameCoordinator], BinarySensorEntity
):
    """ON when it's time to start the stove ahead of an incoming cold snap.

    Stays ON for a 90-minute window after the recommended preheat
    time, so a minute-tick miss doesn't make the flag bounce back
    off. Pair with a HA automation to auto-start the stove (or just
    send a notification).
    """

    _attr_has_entity_name = True
    _attr_name = "Should preheat now"
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_should_preheat_now"

    @property
    def is_on(self) -> bool:
        return self.coordinator.should_preheat_now(self._stove_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "cold_snap_in_hours": self.coordinator.cold_snap_in_hours(),
            "forecast_min_temp_24h": self.coordinator.forecast_min_temp_24h(),
        }
