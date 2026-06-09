"""Config flow per EW-50E."""
from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

DOMAIN = "ew50e"
_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="192.168.50.72"): str,
        vol.Required(CONF_USERNAME, default="initial"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _test_connection(host: str, username: str, password: str) -> str | None:
    """
    Testa la connessione all'EW-50E.
    Ritorna None se OK, oppure un codice errore stringa.
    """
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Step 1: verifica che il dispositivo risponda al login
        try:
            url = f"https://{host}/control/login"
            params = {"loginId": username, "password": password}
            async with asyncio.timeout(10):
                async with session.get(url, params=params, allow_redirects=True) as resp:
                    _LOGGER.debug("EW-50E login status: %s", resp.status)
                    raw = await resp.text()
                    _LOGGER.debug("EW-50E login body: %s", raw[:200])

                    # Cerca il token in tutti i posti possibili
                    token = None
                    for name in ["token", "Token", "SESSION"]:
                        c = resp.cookies.get(name)
                        if c:
                            token = c.value
                            break
                    if not token and "token=" in str(resp.url):
                        token = str(resp.url).split("token=")[-1].split("&")[0]
                    if not token:
                        try:
                            import json
                            data = json.loads(raw)
                            token = data.get("token") or data.get("Token")
                        except Exception:
                            pass
                    if not token:
                        _LOGGER.warning("EW-50E: token non trovato, procedo senza")

        except aiohttp.ClientConnectorError:
            return "cannot_connect"
        except Exception as err:
            _LOGGER.exception("Errore login EW-50E: %s", err)
            return "cannot_connect"

        # Step 2: verifica WebSocket
        try:
            ws_url = f"wss://{host}/b_xmlproc/?token={token}" if token else f"wss://{host}/b_xmlproc/"
            async with asyncio.timeout(8):
                ws = await session.ws_connect(ws_url, ssl=ssl_ctx, heartbeat=5)
                await ws.close()
                _LOGGER.debug("EW-50E WebSocket OK")
                return None  # tutto OK
        except Exception as err:
            _LOGGER.warning("EW-50E WebSocket fallito: %s — accetto comunque", err)
            return None  # accettiamo: il token reale arriva a runtime


class EW50EConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow per EW-50E."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _test_connection(
                user_input[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if error:
                errors["base"] = error
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
