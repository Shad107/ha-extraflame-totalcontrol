"""Climate entity per stove: on/off + target room temperature."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MACHINE_STATE_COOLDOWN,
    MACHINE_STATE_OFF,
    MACHINE_STATE_PREHEAT,
    MACHINE_STATE_RUNNING,
)
from .coordinator import ExtraflameCoordinator, stove_device_info

OFF_STATES = MACHINE_STATE_OFF


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ExtraflameCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ExtraflameClimate(coordinator, stove_id)
        for stove_id in coordinator.data.get("stoves", {})
    )


class ExtraflameClimate(CoordinatorEntity[ExtraflameCoordinator], ClimateEntity):
    _attr_has_entity_name = True
    _attr_name = None  # use the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
    )
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_climate"

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
    def current_temperature(self) -> float | None:
        v = self._param("roomTemp")
        return float(v) if v is not None else None

    @property
    def target_temperature(self) -> float | None:
        v = self._param("targetRoomTemp")
        return float(v) if v is not None else None

    @property
    def hvac_mode(self) -> HVACMode:
        state = self._param("machineState")
        if state is None:
            return HVACMode.OFF
        return HVACMode.OFF if int(state) in OFF_STATES else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        ms = self._param("machineState")
        power = self._param("power")
        if ms is None:
            return HVACAction.OFF
        s = int(ms)
        if s in MACHINE_STATE_OFF:
            return HVACAction.OFF
        if s in MACHINE_STATE_PREHEAT:
            return HVACAction.PREHEATING
        if s in MACHINE_STATE_RUNNING and power is not None and float(power) > 0:
            return HVACAction.HEATING
        if s in MACHINE_STATE_COOLDOWN:
            return HVACAction.IDLE
        return HVACAction.IDLE

    @property
    def available(self) -> bool:
        return bool(self._snap().get("online", False))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator._client.set_room_temp(self._stove_id, float(temp))
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        new_state = 1 if hvac_mode == HVACMode.HEAT else 0
        await self.coordinator._client.set_machine_state(self._stove_id, new_state)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
