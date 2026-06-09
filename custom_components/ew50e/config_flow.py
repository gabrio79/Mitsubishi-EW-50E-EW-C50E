"""Config flow per EW-50E."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

# Punto A: Definizione locale e fissa del DOMAIN per evitare import circolari
DOMAIN = "ew50e"

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="192.168.50.72"): str,
        vol.Required(CONF_USERNAME, default="initial"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class EW50EConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow per EW-50E."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                from . import EW50EClient
                
                client = EW50EClient(
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                await client.login()
                await client.disconnect()
            except ValueError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientConnectorError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Errore imprevisto durante il login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"EW-50E ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
