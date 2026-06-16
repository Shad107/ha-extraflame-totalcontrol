"""Config flow for Extraflame TotalControl 2.0."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from extraflame_totalcontrol import ExtraflameAuthError, ExtraflameClient  # type: ignore

from .const import (
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_USERNAME,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)


class ExtraflameConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
