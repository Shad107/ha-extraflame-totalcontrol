"""Config flow for Extraflame TotalControl 2.0."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from .api_client import ExtraflameAuthError, ExtraflameClient

from homeassistant.helpers import selector

from .const import (
    AGGREGATION_MODES,
    CONF_AGGREGATION_MODE,
    CONF_AUTO_DEADBAND,
    CONF_AUTO_MAX_POWER,
    CONF_AUTO_MIN_POWER,
    CONF_HOME_HEAT_CAPACITY_MJ_PER_K,
    CONF_HUMIDITY_COMFORT_HIGH_PCT,
    CONF_HUMIDITY_COMFORT_LOW_PCT,
    CONF_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PELLET_PCI_KWH_KG,
    CONF_PASSWORD,
    CONF_PELLET_CONSUMPTION_P1_KG_H,
    CONF_PELLET_CONSUMPTION_P2_KG_H,
    CONF_PELLET_CONSUMPTION_P3_KG_H,
    CONF_PELLET_CONSUMPTION_P4_KG_H,
    CONF_PELLET_CONSUMPTION_P5_KG_H,
    CONF_PELLET_HOPPER_CAPACITY_KG,
    CONF_POLL_INTERVAL,
    CONF_PRESETS,
    CONF_TEMP_SENSORS,
    CONF_USERNAME,
    DEFAULT_AGGREGATION_MODE,
    DEFAULT_AUTO_DEADBAND,
    DEFAULT_AUTO_MAX_POWER,
    DEFAULT_AUTO_MIN_POWER,
    DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K,
    DEFAULT_HUMIDITY_COMFORT_HIGH_PCT,
    DEFAULT_HUMIDITY_COMFORT_LOW_PCT,
    DEFAULT_PELLET_CONSUMPTION_P1_KG_H,
    DEFAULT_PELLET_PCI_KWH_KG,
    DEFAULT_PELLET_CONSUMPTION_P2_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P3_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P4_KG_H,
    DEFAULT_PELLET_CONSUMPTION_P5_KG_H,
    DEFAULT_PELLET_HOPPER_CAPACITY_KG,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PRESETS,
    DOMAIN,
    PRESET_NAMES,
)


class ExtraflameConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ExtraflameOptionsFlow":
        # In HA 2025.12+ the ConfigEntry is injected on the parent
        # automatically - instantiating with no args is the supported
        # pattern. We used to pass the entry to __init__ and assign it
        # to self.config_entry, but that attribute is now a property
        # with no setter and that explodes with a 500 in the UI.
        return ExtraflameOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = ExtraflameClient(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            try:
                await client.login()
                stoves = await client.list_stoves()
            except ExtraflameAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await client.close()
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Extraflame ({len(stoves)} stoves)",
                    data=user_input,
                )
            await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): int,
                }
            ),
            errors=errors,
        )


FAN_MODE_CHOICES = {0: "Off", 1: "Auto", 2: "Manuel"}


class ExtraflameOptionsFlow(config_entries.OptionsFlow):
    """User-editable presets. One step, one form, all four presets shown.

    No custom __init__ - HA's flow framework injects ``self.config_entry``
    via the parent class. Assigning it ourselves blows up with an
    ``AttributeError: property has no setter`` on HA 2025.12+.
    """

    def _current(self) -> dict:
        return self.config_entry.options.get(CONF_PRESETS) or DEFAULT_PRESETS

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            new_presets: dict[str, dict] = {}
            for name in PRESET_NAMES:
                new_presets[name] = {
                    "enabled": bool(user_input[f"{name}_enabled"]),
                    "power": int(user_input[f"{name}_power"]),
                    "target_temp": float(user_input[f"{name}_target_temp"]),
                    "fan_mode": int(user_input[f"{name}_fan_mode"]),
                    "fan_speed": int(user_input[f"{name}_fan_speed"]),
                }
            return self.async_create_entry(
                title="",
                data={
                    CONF_PRESETS: new_presets,
                    CONF_AUTO_MIN_POWER: int(user_input[CONF_AUTO_MIN_POWER]),
                    CONF_AUTO_MAX_POWER: int(user_input[CONF_AUTO_MAX_POWER]),
                    CONF_AUTO_DEADBAND: float(user_input[CONF_AUTO_DEADBAND]),
                    CONF_TEMP_SENSORS: user_input.get(CONF_TEMP_SENSORS, []) or [],
                    CONF_HUMIDITY_SENSORS: user_input.get(CONF_HUMIDITY_SENSORS, []) or [],
                    CONF_AGGREGATION_MODE: user_input.get(
                        CONF_AGGREGATION_MODE, DEFAULT_AGGREGATION_MODE
                    ),
                    CONF_OUTDOOR_TEMP_SENSOR: user_input.get(CONF_OUTDOOR_TEMP_SENSOR) or None,
                    CONF_PELLET_HOPPER_CAPACITY_KG: float(
                        user_input.get(CONF_PELLET_HOPPER_CAPACITY_KG, DEFAULT_PELLET_HOPPER_CAPACITY_KG)
                    ),
                    CONF_PELLET_CONSUMPTION_P1_KG_H: float(
                        user_input.get(CONF_PELLET_CONSUMPTION_P1_KG_H, DEFAULT_PELLET_CONSUMPTION_P1_KG_H)
                    ),
                    CONF_PELLET_CONSUMPTION_P2_KG_H: float(
                        user_input.get(CONF_PELLET_CONSUMPTION_P2_KG_H, DEFAULT_PELLET_CONSUMPTION_P2_KG_H)
                    ),
                    CONF_PELLET_CONSUMPTION_P3_KG_H: float(
                        user_input.get(CONF_PELLET_CONSUMPTION_P3_KG_H, DEFAULT_PELLET_CONSUMPTION_P3_KG_H)
                    ),
                    CONF_PELLET_CONSUMPTION_P4_KG_H: float(
                        user_input.get(CONF_PELLET_CONSUMPTION_P4_KG_H, DEFAULT_PELLET_CONSUMPTION_P4_KG_H)
                    ),
                    CONF_PELLET_CONSUMPTION_P5_KG_H: float(
                        user_input.get(CONF_PELLET_CONSUMPTION_P5_KG_H, DEFAULT_PELLET_CONSUMPTION_P5_KG_H)
                    ),
                    CONF_HUMIDITY_COMFORT_LOW_PCT: float(
                        user_input.get(CONF_HUMIDITY_COMFORT_LOW_PCT, DEFAULT_HUMIDITY_COMFORT_LOW_PCT)
                    ),
                    CONF_HUMIDITY_COMFORT_HIGH_PCT: float(
                        user_input.get(CONF_HUMIDITY_COMFORT_HIGH_PCT, DEFAULT_HUMIDITY_COMFORT_HIGH_PCT)
                    ),
                    CONF_PELLET_PCI_KWH_KG: float(
                        user_input.get(CONF_PELLET_PCI_KWH_KG, DEFAULT_PELLET_PCI_KWH_KG)
                    ),
                    CONF_HOME_HEAT_CAPACITY_MJ_PER_K: float(
                        user_input.get(CONF_HOME_HEAT_CAPACITY_MJ_PER_K, DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K)
                    ),
                },
            )

        current = self._current()
        schema_dict: dict[Any, Any] = {}
        for name in PRESET_NAMES:
            p = current.get(name) or DEFAULT_PRESETS[name]
            schema_dict[vol.Required(f"{name}_enabled", default=p.get("enabled", True))] = bool
            schema_dict[vol.Required(f"{name}_power", default=p.get("power", 3))] = vol.All(
                int, vol.Range(min=1, max=5)
            )
            schema_dict[vol.Required(f"{name}_target_temp", default=p.get("target_temp", 21))] = vol.All(
                vol.Coerce(float), vol.Range(min=5, max=35)
            )
            schema_dict[vol.Required(f"{name}_fan_mode", default=p.get("fan_mode", 1))] = vol.In(
                FAN_MODE_CHOICES
            )
            schema_dict[vol.Required(f"{name}_fan_speed", default=p.get("fan_speed", 0))] = vol.All(
                int, vol.Range(min=0, max=6)
            )
        opts = self.config_entry.options
        schema_dict[vol.Required(
            CONF_AUTO_MIN_POWER,
            default=opts.get(CONF_AUTO_MIN_POWER, DEFAULT_AUTO_MIN_POWER),
        )] = vol.All(int, vol.Range(min=1, max=5))
        schema_dict[vol.Required(
            CONF_AUTO_MAX_POWER,
            default=opts.get(CONF_AUTO_MAX_POWER, DEFAULT_AUTO_MAX_POWER),
        )] = vol.All(int, vol.Range(min=1, max=5))
        schema_dict[vol.Required(
            CONF_AUTO_DEADBAND,
            default=opts.get(CONF_AUTO_DEADBAND, DEFAULT_AUTO_DEADBAND),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0))

        # ----- v0.2.0 sensor aggregation section -----
        # Picker shows any sensor in HA with device_class temperature /
        # humidity, grouped by area badge - so Tado TRV heads, Aqara
        # probes, ESPHome customs, anything appears automatically.
        schema_dict[vol.Optional(
            CONF_TEMP_SENSORS,
            default=opts.get(CONF_TEMP_SENSORS, []),
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="temperature",
                multiple=True,
            )
        )
        schema_dict[vol.Optional(
            CONF_HUMIDITY_SENSORS,
            default=opts.get(CONF_HUMIDITY_SENSORS, []),
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="humidity",
                multiple=True,
            )
        )
        schema_dict[vol.Required(
            CONF_AGGREGATION_MODE,
            default=opts.get(CONF_AGGREGATION_MODE, DEFAULT_AGGREGATION_MODE),
        )] = vol.In(list(AGGREGATION_MODES))

        # Outdoor temperature - single source for v0.3.0 RC model fit
        # and v0.4.0 anticipatory pre-heating. Default suggestion left
        # empty so users with no outdoor probe stay opted-out.
        schema_dict[vol.Optional(
            CONF_OUTDOOR_TEMP_SENSOR,
            default=opts.get(CONF_OUTDOOR_TEMP_SENSOR) or vol.UNDEFINED,
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="temperature",
                multiple=False,
            )
        )

        # ----- v0.2.6 pellet hopper tracking section -----
        # Capacity is per-stove (Teodora Evo ships 14 kg by spec, some
        # users observe ~12 kg of usable volume). P1..P5 rates are
        # interpolated linearly to estimate consumption at the live
        # power level.
        schema_dict[vol.Required(
            CONF_PELLET_HOPPER_CAPACITY_KG,
            default=opts.get(CONF_PELLET_HOPPER_CAPACITY_KG, DEFAULT_PELLET_HOPPER_CAPACITY_KG),
        )] = vol.All(vol.Coerce(float), vol.Range(min=1.0, max=60.0))
        schema_dict[vol.Required(
            CONF_PELLET_CONSUMPTION_P1_KG_H,
            default=opts.get(CONF_PELLET_CONSUMPTION_P1_KG_H, DEFAULT_PELLET_CONSUMPTION_P1_KG_H),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0))
        schema_dict[vol.Required(
            CONF_PELLET_CONSUMPTION_P2_KG_H,
            default=opts.get(CONF_PELLET_CONSUMPTION_P2_KG_H, DEFAULT_PELLET_CONSUMPTION_P2_KG_H),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0))
        schema_dict[vol.Required(
            CONF_PELLET_CONSUMPTION_P3_KG_H,
            default=opts.get(CONF_PELLET_CONSUMPTION_P3_KG_H, DEFAULT_PELLET_CONSUMPTION_P3_KG_H),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0))
        schema_dict[vol.Required(
            CONF_PELLET_CONSUMPTION_P4_KG_H,
            default=opts.get(CONF_PELLET_CONSUMPTION_P4_KG_H, DEFAULT_PELLET_CONSUMPTION_P4_KG_H),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0))
        schema_dict[vol.Required(
            CONF_PELLET_CONSUMPTION_P5_KG_H,
            default=opts.get(CONF_PELLET_CONSUMPTION_P5_KG_H, DEFAULT_PELLET_CONSUMPTION_P5_KG_H),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0))

        # ----- v0.2.7 humidity comfort band -----
        # ASHRAE comfort range is 30..60% RH in winter; defaults match
        # that with a touch of slack at the high end for older homes.
        schema_dict[vol.Required(
            CONF_HUMIDITY_COMFORT_LOW_PCT,
            default=opts.get(CONF_HUMIDITY_COMFORT_LOW_PCT, DEFAULT_HUMIDITY_COMFORT_LOW_PCT),
        )] = vol.All(vol.Coerce(float), vol.Range(min=10.0, max=50.0))
        schema_dict[vol.Required(
            CONF_HUMIDITY_COMFORT_HIGH_PCT,
            default=opts.get(CONF_HUMIDITY_COMFORT_HIGH_PCT, DEFAULT_HUMIDITY_COMFORT_HIGH_PCT),
        )] = vol.All(vol.Coerce(float), vol.Range(min=40.0, max=90.0))

        # ----- v0.4.0 thermal prediction parameters -----
        schema_dict[vol.Required(
            CONF_PELLET_PCI_KWH_KG,
            default=opts.get(CONF_PELLET_PCI_KWH_KG, DEFAULT_PELLET_PCI_KWH_KG),
        )] = vol.All(vol.Coerce(float), vol.Range(min=3.0, max=6.0))
        schema_dict[vol.Required(
            CONF_HOME_HEAT_CAPACITY_MJ_PER_K,
            default=opts.get(CONF_HOME_HEAT_CAPACITY_MJ_PER_K, DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K),
        )] = vol.All(vol.Coerce(float), vol.Range(min=0.5, max=50.0))

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
