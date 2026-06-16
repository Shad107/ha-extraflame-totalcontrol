"""Number entity for the main fan speed (0..6 typical on Extraflame).

The cloud accepts arbitrary integer values for ``mainFanSpeed`` via the
``settings`` sendCommand topic. The actual range depends on the stove
model; Teodora Evo runs 0..6 (0 = off, 6 = max). Other models may
clamp differently — the API never reported an error in tests though,
so the slider stays soft-bounded by HA.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExtraflameCoordinator, stove_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ExtraflameMainFanSpeedNumber(coordinator, stove_id)
        for stove_id in coordinator.data.get("stoves", {})
    )


class ExtraflameMainFanSpeedNumber(CoordinatorEntity[ExtraflameCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Main fan speed"
    _attr_icon = "mdi:fan"
    _attr_native_min_value = 0
    _attr_native_max_value = 6
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_main_fan_speed"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def native_value(self) -> float | None:
        params = (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {}).get("parameters") or {}
        p = params.get("mainFanSpeed")
        if p is None or p.value is None:
            return None
        try:
            return float(p.value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._client.send_command(
            self._stove_id, "settings", {"mainFanSpeed": int(value)}
        )
        await self.coordinator.async_request_refresh()
