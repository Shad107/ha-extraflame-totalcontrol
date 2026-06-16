"""Auto-modulation switch.

The Extraflame stove itself does NOT pick a power level between P1
and P5 automatically — the user-set ``targetPower`` stays put while
WORK is active. Specialists discourage P1 (incomplete combustion,
soot, tar) so leaving the stove on P1 24/7 is a bad idea, and so is
hand-picking P5 when the room is already comfortable.

When this switch is ON, the integration drives ``targetPower`` from
the room/setpoint delta on every coordinator update, emulating the
modulation the stove can't do itself. Bounds (min/max) and the
hysteresis dead-band are configurable from the integration's
Options page. The default floor is P2 to keep combustion clean.

State persists across HA restarts via RestoreEntity.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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
        ExtraflameAutoModulationSwitch(coordinator, stove_id)
        for stove_id in coordinator.data.get("stoves", {})
    )


class ExtraflameAutoModulationSwitch(
    CoordinatorEntity[ExtraflameCoordinator], SwitchEntity, RestoreEntity
):
    _attr_has_entity_name = True
    _attr_name = "Auto modulation"
    _attr_icon = "mdi:auto-mode"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_auto_modulation"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore persisted on/off across HA restarts.
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
        # Register ourselves with the coordinator so it can apply auto-
        # modulation after every poll without needing hass.states.get.
        self.coordinator.register_auto_modulation(self._stove_id, self)

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.unregister_auto_modulation(self._stove_id)
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        # Apply once immediately so the stove doesn't have to wait for
        # the next 30 s tick to see the new target.
        await self.coordinator.apply_auto_modulation(self._stove_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
