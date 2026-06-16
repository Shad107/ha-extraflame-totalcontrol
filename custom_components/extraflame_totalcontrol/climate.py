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
    CONF_PRESETS,
    DEFAULT_PRESETS,
    DOMAIN,
    MACHINE_STATE_COOLDOWN,
    MACHINE_STATE_OFF,
    MACHINE_STATE_PREHEAT,
    MACHINE_STATE_RUNNING,
    PRESET_NAMES,
)
from .coordinator import ExtraflameCoordinator, stove_device_info

OFF_STATES = MACHINE_STATE_OFF
PRESET_NONE = "none"


def _recipe_from_options(p: dict) -> dict[str, int]:
    """Translate an options-flow preset dict into a sendCommand payload."""
    out: dict[str, int] = {
        "targetPower": int(p["power"]),
        "targetRoomTemp": float(p["target_temp"]),
        "mainFanMode": int(p["fan_mode"]),
    }
    # Manual fan speed (mode == 2) gets pushed too; auto/off ignore it.
    if int(p["fan_mode"]) >= 2:
        out["mainFanSpeed"] = int(p["fan_speed"])
    return out


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
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_unique_id = f"extraflame_{stove_id}_climate"
        # Re-render preset_modes when the user edits the options flow.
        coordinator.config_entry.async_on_unload(
            coordinator.config_entry.add_update_listener(self._async_options_changed)
        )

    async def _async_options_changed(self, hass, entry) -> None:  # noqa: ARG002
        # The OptionsFlow updates entry.options in place; just push a
        # state update so HA's frontend re-reads preset_modes.
        self.async_write_ha_state()

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

    def _user_presets(self) -> dict[str, dict]:
        opts = (
            self.coordinator.config_entry.options.get(CONF_PRESETS)
            if self.coordinator.config_entry
            else None
        ) or DEFAULT_PRESETS
        # Force the canonical order of PRESET_NAMES (eco→silence→confort→boost).
        return {n: opts.get(n, DEFAULT_PRESETS[n]) for n in PRESET_NAMES}

    @property
    def preset_modes(self) -> list[str]:
        return [PRESET_NONE] + [
            n for n, p in self._user_presets().items() if p.get("enabled", True)
        ]

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
            tr = float(target_room)
            fm = int(float(fan_mode))
            fs = int(float(fan_speed)) if fan_speed is not None else None
        except (TypeError, ValueError):
            return PRESET_NONE
        for name, p in self._user_presets().items():
            if not p.get("enabled", True):
                continue
            if (
                int(p["power"]) == tp
                and abs(float(p["target_temp"]) - tr) < 0.5
                and int(p["fan_mode"]) == fm
                and (int(p["fan_mode"]) < 2 or int(p["fan_speed"]) == fs)
            ):
                return name
        return PRESET_NONE

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_NONE:
            return
        presets = self._user_presets()
        p = presets.get(preset_mode)
        if not p or not p.get("enabled", True):
            return
        await self.coordinator._client.send_command(
            self._stove_id, "settings", _recipe_from_options(p)
        )
        await self.coordinator.async_request_refresh()
