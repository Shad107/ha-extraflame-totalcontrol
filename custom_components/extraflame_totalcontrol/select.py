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

# mainFanMode mapping. The Micronova convention varies by model; on a
# Teodora Evo the cloud reports `1` while the app shows "Auto", so 0 is
# off, 1 is auto, and 2+ is manual (manual speed is then driven by the
# separate mainFanSpeed param). Other models may report 0=off, 1..5=manual,
# 6=auto — open an issue with observed values if your readings differ.
FAN_MODE_OPTIONS = {0: "Off", 1: "Auto", 2: "Manuel"}
FAN_MODE_NAMES = list(FAN_MODE_OPTIONS.values())
FAN_MODE_BY_NAME = {v: k for k, v in FAN_MODE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove_id in coordinator.data.get("stoves", {}):
        entities.append(ExtraflamePowerSelect(coordinator, stove_id))
        entities.append(ExtraflameMainFanModeSelect(coordinator, stove_id))
    async_add_entities(entities)


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


class ExtraflameMainFanModeSelect(CoordinatorEntity[ExtraflameCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Main fan mode"
    _attr_options = FAN_MODE_NAMES
    _attr_icon = "mdi:fan-auto"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_main_fan_mode"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    @property
    def current_option(self) -> str | None:
        params = (self.coordinator.data or {}).get("stoves", {}).get(self._stove_id, {}).get("parameters") or {}
        p = params.get("mainFanMode")
        if p is None or p.value is None:
            return None
        try:
            n = int(float(p.value))
        except (TypeError, ValueError):
            return None
        if n in FAN_MODE_OPTIONS:
            return FAN_MODE_OPTIONS[n]
        # Manual speeds >2 reported as a single "Manuel" bucket
        return "Manuel" if n > 1 else None

    async def async_select_option(self, option: str) -> None:
        if option not in FAN_MODE_BY_NAME:
            return
        await self.coordinator._client.send_command(
            self._stove_id, "settings", {"mainFanMode": FAN_MODE_BY_NAME[option]}
        )
        await self.coordinator.async_request_refresh()
