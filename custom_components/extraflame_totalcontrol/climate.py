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

# Presets bundle a coherent triplet of (targetPower, targetRoomTemp,
# mainFanMode[, mainFanSpeed]) so the user doesn't have to tune each
# parameter individually for common scenarios.
#
# Mental model of fan-vs-target: higher target temperature → cosier,
# quieter setup → fan stays auto/low; lower target → more circulation
# wanted → fan auto suffices, no need to manually crank it. Boost is
# the explicit "warm-up fast" override that drops to manual max fan.
PRESETS: dict[str, dict[str, int]] = {
    "eco":       {"targetPower": 1, "targetRoomTemp": 18, "mainFanMode": 1},
    "silence":   {"targetPower": 2, "targetRoomTemp": 20, "mainFanMode": 1},
    "confort":   {"targetPower": 3, "targetRoomTemp": 21, "mainFanMode": 1},
    "boost":     {"targetPower": 5, "targetRoomTemp": 24, "mainFanMode": 2, "mainFanSpeed": 6},
}
PRESET_NONE = "none"


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
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = [PRESET_NONE, *PRESETS.keys()]
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

    @property
    def preset_mode(self) -> str:
        target_power = self._param("targetPower")
        target_room = self._param("targetRoomTemp")
        fan_mode = self._param("mainFanMode")
        fan_speed = self._param("mainFanSpeed")
        if any(v is None for v in (target_power, target_room, fan_mode)):
            return PRESET_NONE
        try:
            tp = int(float(target_power))
            tr = int(float(target_room))
            fm = int(float(fan_mode))
            fs = int(float(fan_speed)) if fan_speed is not None else None
        except (TypeError, ValueError):
            return PRESET_NONE
        for name, recipe in PRESETS.items():
            if (
                recipe.get("targetPower") == tp
                and recipe.get("targetRoomTemp") == tr
                and recipe.get("mainFanMode") == fm
                and ("mainFanSpeed" not in recipe or recipe["mainFanSpeed"] == fs)
            ):
                return name
        return PRESET_NONE

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_NONE:
            return
        recipe = PRESETS.get(preset_mode)
        if not recipe:
            return
        # The cloud's sendCommand/settings accepts a dict — one round-trip
        # is enough to push the whole preset at once.
        await self.coordinator._client.send_command(
            self._stove_id, "settings", dict(recipe)
        )
        await self.coordinator.async_request_refresh()
