"""Config Flow per l'integrazione Mitsubishi EW-50E / EW-C50E."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN, EW50EAuthError, EW50EClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="192.168.50.72"): str,
        vol.Required(CONF_USERNAME, default="initial"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _test_connection(host: str, username: str, password: str) -> str | None:
    """Verifica la connessione e le credenziali sull'EW-50E senza bloccare l'event loop."""
    client = EW50EClient(host, username, password)
    try:
        await client.connect()
        return None
    except EW50EAuthError:
        return "invalid_auth"
    except (aiohttp.ClientError, TimeoutError):
        return "cannot_connect"
    except ValueError as err:
        _LOGGER.warning("EW-50E login rifiutato su %s: %s", host, err)
        return "invalid_auth"
    except Exception as err:
        _LOGGER.exception("Errore imprevisto durante test connessione EW-50E: %s", err)
        return "cannot_connect"
    finally:
        await client.disconnect()


class EW50EConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il flusso di configurazione UI per Mitsubishi EW-50E."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            error = await _test_connection(host, username, password)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"EW-50E ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
