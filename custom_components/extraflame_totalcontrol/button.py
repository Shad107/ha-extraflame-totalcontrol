"""Action buttons exposed per stove.

For now the only button is *Refill pellet hopper* - pressed by the user
right after they finish topping up the hopper. It resets the integrator
to the configured capacity so the level/autonomy sensors start counting
down from a known state.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    entities: list[ButtonEntity] = []
    for stove_id in coordinator.data.get("stoves", {}):
        entities.append(ExtraflameRefillPelletButton(coordinator, stove_id))
        entities.append(ExtraflameLearnInertiaButton(coordinator, stove_id))
    async_add_entities(entities)


class ExtraflameRefillPelletButton(
    CoordinatorEntity[ExtraflameCoordinator], ButtonEntity
):
    _attr_has_entity_name = True
    _attr_name = "Refill pellet"
    _attr_icon = "mdi:basket-fill"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_refill_pellet"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    async def async_press(self) -> None:
        await self.coordinator.async_refill_pellet(self._stove_id)


class ExtraflameLearnInertiaButton(
    CoordinatorEntity[ExtraflameCoordinator], ButtonEntity
):
    """Fit the home's thermal RC model from HA Recorder history.

    Reads the last 14 days of indoor aggregate temperature, outdoor
    temperature, and stove state, filters out periods when the stove
    was burning, and fits the natural decay constant of the home. Safe
    to run year-round - even in summer the indoor temperature tracks
    the outdoor diurnal cycle through the envelope, so tau converges
    without needing a heating session.
    """

    _attr_has_entity_name = True
    _attr_name = "Learn inertia"
    _attr_icon = "mdi:school"

    def __init__(self, coordinator: ExtraflameCoordinator, stove_id: str) -> None:
        super().__init__(coordinator)
        self._stove_id = stove_id
        self._attr_unique_id = f"extraflame_{stove_id}_learn_inertia"
        stove = coordinator.data["stoves"][stove_id]["stove"]
        self._attr_device_info = stove_device_info(stove)

    async def async_press(self) -> None:
        meta = await self.coordinator.async_learn_inertia(self._stove_id)
        if meta.get("error"):
            import logging
            logging.getLogger(__name__).warning(
                "inertia fit for %s failed: %s", self._stove_id, meta["error"]
            )
