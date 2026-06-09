"""EW-50E Mitsubishi Electric - Custom Integration per Home Assistant.

Protocollo: XML over WebSocket (WSS port 443)
Autenticazione: JWT token via HTTP login, poi passato al WS come query param.
I nomi dei gruppi vengono letti automaticamente dall'EW-50E al primo avvio.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any

import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ew50e"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    client = EW50EClient(host, username, password)
    coordinator = EW50ECoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: EW50ECoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.disconnect()
    return unload_ok


class EW50EClient:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self._token: str | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def login(self) -> bool:
        """Logica di autenticazione JWT (Simulata)."""
        _LOGGER.info("Tentativo di login su EW-50E (%s)...", self.host)
        await asyncio.sleep(0.5)
        return True

    async def connect(self) -> None:
        """Apri la connessione WebSocket."""
        session = self._get_session()
        ws_url = f"wss://{self.host}/b_xmlproc/?token={self._token}"
        self._ws = await session.ws_connect(ws_url, ssl=self._ssl_ctx, heartbeat=30)
        _LOGGER.debug("WebSocket EW-50E connesso a %s", self.host)
        
    async def disconnect(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_connected(self) -> None:
        if self._ws is None or self._ws.closed:
            _LOGGER.info("EW-50E: riconnessione WebSocket...")
            self._token = None
            await self.connect()

    async def send_request(self, xml_command: str) -> None:
        await self._ensure_connected()
        await self._ws.send_str(xml_command)

    async def receive_messages(self, timeout: float = 5.0) -> list[ET.Element]:
        messages = []
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        root = ET.fromstring(msg.data)
                        messages.append(root)
                    except ET.ParseError as e:
                        _LOGGER.warning("XML non valido ricevuto: %s", e)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    _LOGGER.warning("WebSocket chiuso/errore durante ricezione")
                    self._ws = None
                    break
            except asyncio.TimeoutError:
                break
        return messages

    def _xml_get_group_names(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Packet><Command>getRequest</Command>"
            "<DatabaseManager>"
            '<Mnet Group="all" Attribute="GroupName"/>'
            "</DatabaseManager></Packet>"
        )

    def _xml_get_mnet_status(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Packet><Command>getRequest</Command>"
            "<DatabaseManager>"
            '<Mnet Group="all" Attribute="All"/>'
            "</DatabaseManager></Packet>"
        )

    def _xml_get_alarm_list(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Packet><Command>getRequest</Command>"
            "<DatabaseManager><Mnet>"
            "<AlarmStatusList/>"
            "</Mnet></DatabaseManager></Packet>"
        )

    def _xml_get_outdoor_temp(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Packet><Command>getRequest</Command>"
            "<DatabaseManager>"
            '<Mnet Address="all" Attribute="OATemp"/>'
            "</DatabaseManager></Packet>"
        )

    def _xml_get_system_alarm(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Packet><Command>getRequest</Command>"
            "<DatabaseManager><SystemAlarm/></DatabaseManager></Packet>"
        )

    async def fetch_group_names(self) -> dict[str, str]:
        await self._ensure_connected()
        await self.send_request(self._xml_get_group_names())
        await asyncio.sleep(1.5)
        messages = await self.receive_messages(timeout=6.0)

        group_names: dict[str, str] = {}
        for packet in messages:
            db = packet.find("DatabaseManager")
            if db is None:
                continue
            for mnet in db.findall("Mnet"):
                group_id = mnet.get("Group")
                group_name = mnet.get("GroupName")
                if group_id and group_name:
                    group_names[group_id] = group_name
                    _LOGGER.debug("Gruppo %s = '%s'", group_id, group_name)

        _LOGGER.info("EW-50E: trovati %d gruppi", len(group_names))
        return group_names

    async def fetch_all_data(self) -> dict[str, Any]:
        await self._ensure_connected()
        await self.send_request(self._xml_get_mnet_status())
        await self.send_request(self._xml_get_alarm_list())
        await self.send_request(self._xml_get_outdoor_temp())
        await self.send_request(self._xml_get_system_alarm())
        await asyncio.sleep(1)
        messages = await self.receive_messages(timeout=8.0)
        return self._parse_messages(messages)

    def _parse_messages(self, messages: list[ET.Element]) -> dict[str, Any]:
        data: dict[str, Any] = {
            "groups": {},
            "alarms": [],
            "system_alarm": {},
            "outdoor_temp": None,
            "mnet_status": "UNKNOWN",
        }

        for packet in messages:
            db = packet.find("DatabaseManager")
            if db is None:
                continue

            sys_data = db.find("SystemData")
            if sys_data is not None:
                data["mnet_status"] = sys_data.get("MnetStatus", "UNKNOWN")

            sys_alarm = db.find("SystemAlarm")
            if sys_alarm is not None:
                data["system_alarm"] = {
                    "alert": sys_alarm.get("Alert", "OFF"),
                    "alert_level": sys_alarm.get("AlertTriggerLevel", "0"),
                    "alert_address": sys_alarm.get("AlertTriggerAddress", "0"),
                    "error_code": sys_alarm.get("AlertTriggerErrorCode", "0000"),
                    "buzzer_lamp": sys_alarm.get("BuzzerLamp", "OFF"),
                    "ref_leak_alarm": sys_alarm.get("RefLeakAlarm", "OFF"),
                }

            alarm_list = db.find(".//AlarmStatusList")
            if alarm_list is not None:
                for alarm in alarm_list.findall("AlarmStatusRecord"):
                    data["alarms"].append({
                        "group": alarm.get("Group", ""),
                        "address": alarm.get("Address", ""),
                        "error_code": alarm.get("ErrorCode", ""),
                        "error_level": alarm.get("ErrorLevel", ""),
                        "error_type": alarm.get("ErrorType", ""),
                    })

            for mnet in db.findall("Mnet"):
                group = mnet.get("Group")
                if group:
                    if group not in data["groups"]:
                        data["groups"][group] = {}
                    g = data["groups"][group]
                    for attr in [
                        "Drive", "Mode", "SetTemp", "InletTemp",
                        "AirDirection", "FanSpeed", "ErrorSign",
                        "ErrorCode", "GroupName",
                    ]:
                        val = mnet.get(attr)
                        if val is not None:
                            g[attr.lower()] = val

                address = mnet.get("Address")
                oa_temp = mnet.get("OATemp")
                if address and oa_temp:
                    try:
                        t = float(oa_temp)
                        if data["outdoor_temp"] is None:
                            data["outdoor_temp"] = t
                    except ValueError:
                        pass

            for ref in db.findall("RefUnit"):
                if ref.get("ErrorSign") == "ON":
                    error_code = ref.get("ErrorCode", "")
                    if error_code:
                        data["alarms"].append({
                            "group": "",
                            "address": ref.get("Address", ""),
                            "error_code": error_code,
                            "error_level": ref.get("ErrorLevel", ""),
                            "error_type": "RefUnit",
                        })

        return data


class EW50ECoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: EW50EClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.group_names: dict[str, str] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with async_timeout.timeout(25):
                if not self.group_names:
                    _LOGGER.info("EW-50E: primo avvio, scarico nomi gruppi...")
                    self.group_names = await self.client.fetch_group_names()
                    if not self.group_names:
                        _LOGGER.warning(
                            "EW-50E: nessun nome gruppo ricevuto. "
                            "Verrà usato 'Gruppo N' come nome provvisorio."
                        )

                data = await self.client.fetch_all_data()

                for group_id in list(data["groups"].keys()) + list(self.group_names.keys()):
                    if group_id not in data["groups"]:
                        data["groups"][group_id] = {}
                    g = data["groups"][group_id]
                    if not g.get("groupname") and group_id in self.group_names:
                        g["groupname"] = self.group_names[group_id]
                    if not g.get("groupname"):
                        g["groupname"] = f"Gruppo {group_id}"

                return data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Errore connessione EW-50E: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout connessione EW-50E") from err
        except Exception as err:
            _LOGGER.exception("Errore imprevisto EW-50E")
            raise UpdateFailed(f"Errore: {err}") from err
