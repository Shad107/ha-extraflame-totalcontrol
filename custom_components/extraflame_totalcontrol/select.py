"""Power level selector (P1..P5) per stove."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExtraflameCoordinator, stove_device_info

POWER_OPTIONS = ["P1", "P2", "P3", "P4", "P5"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ExtraflamePowerSelect(coordinator, stove_id)
        for stove_id in coordinator.data.get("stoves", {})
    )


class ExtraflamePowerSelect(CoordinatorEntity[ExtraflameCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_options = POWER_OPTIONS
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_power"

    @property
    def current_option(self) -> str | None:
        params = (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {}).get("parameters") or {}
        p = params.get("targetPower") or params.get("power")
        if p is None or p.value is None:
            return None
        try:
            n = int(float(p.value))
        except (TypeError, ValueError):
            return None
        if 1 <= n <= 5:
            return f"P{n}"
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in POWER_OPTIONS:
            return
        level = int(option.lstrip("P"))
        await self.coordinator._client.set_power(self._stove_id, level)
        await self.coordinator.async_request_refresh()
