"""Inizializzazione del componente Mitsubishi EW-50E."""
from __future__ import annotations

import logging
import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

DOMAIN = "ew50e"
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_LOGGER = logging.getLogger(__name__)


class EW50EClient:
    """Classe Client per gestire la connessione WebSocket/HTTP con EW-50E."""

    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password

    async def login(self) -> bool:
        """Logica di autenticazione JWT (Simulata)."""
        _LOGGER.info("Tentativo di login su EW-50E (%s)...", self.host)
        await asyncio.sleep(0.5)
        return True

    async def fetch_data(self) -> dict:
        """Simula il recupero dei dati XML via WebSocket per tutti i 17 gruppi."""
        simulated_groups = {}
        for idx in range(1, 18):
            str_idx = str(idx)
            # Imposta HEAT per la casa e il bilocale, COOL per gli studi medici e aree comuni
            mode = "HEAT" if idx in [6, 7, 8, 9, 10] else "COOL"
            simulated_groups[str_idx] = {
                "drive": "OFF", 
                "errorsign": "OFF", 
                "temp": 21.5, 
                "mode": mode,
                "fanspeed": "MID",
                "airdirection": "AUTO",
                "errorcode": ""
            }
            
        return {
            "groups": simulated_groups,
            "alarms": [],
            "system": {"outdoor_temp": 18.5, "status": "NORMALE", "alarm_count": 0}
        }

    async def disconnect(self):
        """Chiude la connessione WebSocket."""
        _LOGGER.info("Disconnessione da EW-50E.")
        await asyncio.sleep(0.1)


class EW50ECoordinator(DataUpdateCoordinator):
    """Coordinator per gestire l'aggiornamento centralizzato dei dati."""

    def __init__(self, hass: HomeAssistant, client: EW50EClient) -> None:
        """Inizializzazione del Coordinator con tutte le 17 zone."""
        self.client = client
        
        self.group_names: dict[str, str] = {
            "1": "Studio 1 (Roggero)",
            "2": "Studio 2 (Savernini)",
            "3": "Studio 3",
            "4": "Studio 4 (Fisio)",
            "5": "Sala Aspetto",
            "6": "Casa - Soggiorno",
            "7": "Casa - Camera Greta",
            "8": "Casa - Camera Matrimoniale",
            "9": "Bilocale - Soggiorno",
            "10": "Bilocale - Camera",
            "11": "Studio 5",
            "12": "Studio 6",
            "13": "Corridoio Studi",
            "14": "Servizi Igienici",
            "15": "Zona Server / IT",
            "16": "Ingresso Principale",
            "17": "Locale Tecnico"
        }
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self) -> dict:
        """Recupera i dati dal client."""
        try:
            return await self.client.fetch_data()
        except Exception as err:
            raise UpdateFailed(f"Errore durante l'aggiornamento dati EW-50E: {err}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'istanza di EW-50E da una Config Entry (UI)."""
    hass.data.setdefault(DOMAIN, {})

    client = EW50EClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    coordinator = EW50ECoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove un'istanza dell'integrazione."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
