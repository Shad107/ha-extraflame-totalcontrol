"""Extraflame TotalControl 2.0 HA custom component.

Status: scaffolding. config_flow + coordinator are implemented in this
v0.1; climate/sensor entities are TODO and tracked at
https://github.com/Shad107/ha-extraflame-totalcontrol/issues
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ExtraflameCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ExtraflameCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator: ExtraflameCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return ok
