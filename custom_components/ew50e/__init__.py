"""EW-50E Mitsubishi Electric - Custom Integration per Home Assistant.

Versione semplificata: monitora solo stati e anomalie.
Non legge piu' temperature (esterna/ingresso) ne' setpoint.
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

# Nomi gruppi configurati sull'EW-50E (fallback hardcodato)
KNOWN_GROUP_NAMES: dict[str, str] = {
    "1": "Farmacia - Magazzino",
    "2": "Farmacia - Cassettie",
    "3": "Farmacia - Autoanalisi",
    "4": "Farmacia - Galenico",
    "5": "Farmacia - Bancone",
    "6": "Farmacia - Isola Centrale",
    "7": "Farmacia - Porta Automatica",
    "8": "Farmacia - MammaBambino",
    "9": "Casa - Soggiorno",
    "10": "Casa - Camera Greta",
    "11": "Casa - Camera Matrimoniale",
    "12": "Bilocale - Soggiorno",
    "13": "Studio 1 - Roggero",
    "14": "Studio 3",
    "15": "Studio 2 - Savernini",
    "16": "Studio 4 - Fisio",
    "17": "Studi - Sala Aspetto",
}


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = EW50EClient(entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
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
        self._ssl_ctx: ssl.SSLContext | None = None

    def _get_ssl_ctx(self) -> ssl.SSLContext:
        if self._ssl_ctx is None:
            self._ssl_ctx = _make_ssl_context()
        return self._ssl_ctx

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._get_ssl_ctx())
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def login(self) -> bool:
        _LOGGER.info("EW-50E: login su %s...", self.host)
        session = self._get_session()
        url = f"https://{self.host}/servlet/Login"
        auth = aiohttp.BasicAuth(self.username, self.password)
        async with async_timeout.timeout(10):
            async with session.get(url, auth=auth) as resp:
                if resp.status != 200:
                    raise ValueError(f"Login fallito, status={resp.status}")
                token = (await resp.text()).strip()
                if not token:
                    raise ValueError("Token vuoto ricevuto dal login")
                self._token = token
                return True

    async def connect(self) -> None:
        if not self._token:
            await self.login()
        session = self._get_session()
        ws_url = f"wss://{self.host}/b_xmlproc/?token={self._token}"
        self._ws = await session.ws_connect(ws_url, ssl=self._get_ssl_ctx(), heartbeat=30)
        _LOGGER.debug("EW-50E: WebSocket connesso a %s", self.host)

    async def disconnect(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_connected(self) -> None:
        if self._ws is None or self._ws.closed:
            _LOGGER.info("EW-50E: riconnessione...")
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
                        _LOGGER.warning("XML non valido: %s", e)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    _LOGGER.warning("WebSocket chiuso/errore: %s", msg.type)
                    self._ws = None
                    break
            except asyncio.TimeoutError:
                break
        return messages

    def _xml_get_alarm_list(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><Packet><Command>getRequest</Command><DatabaseManager><Mnet><AlarmStatusList/></Mnet></DatabaseManager></Packet>'

    def _xml_get_system_alarm(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><Packet><Command>getRequest</Command><DatabaseManager><SystemAlarm/></DatabaseManager></Packet>'

    async def discover_groups(self) -> dict[str, str]:
        """
        Scopre i gruppi attivi ascoltando i notifyRequest iniziali,
        poi li arricchisce con i nomi noti. Gruppi non nei notify
        vengono comunque aggiunti se presenti in KNOWN_GROUP_NAMES.
        """
        await self._ensure_connected()

        # Ascolta i notify iniziali per scoprire gruppi attivi
        _LOGGER.info("EW-50E: ascolto notify iniziali...")
        initial = await self.receive_messages(timeout=8.0)

        found_groups: set[str] = set()
        for packet in initial:
            db = packet.find("DatabaseManager")
            if db is None:
                continue
            for mnet in db.findall("Mnet"):
                gid = mnet.get("Group")
                if gid:
                    found_groups.add(gid)

        _LOGGER.info("EW-50E: gruppi da notify: %s", found_groups)

        # Usa tutti i gruppi noti come base (1-17)
        # I notify potrebbero non coprirli tutti
        all_groups = set(KNOWN_GROUP_NAMES.keys()) | found_groups

        group_names: dict[str, str] = {}
        for gid in sorted(all_groups, key=lambda x: int(x) if x.isdigit() else 0):
            # Usa il nome noto se disponibile
            if gid in KNOWN_GROUP_NAMES:
                group_names[gid] = KNOWN_GROUP_NAMES[gid]
            else:
                group_names[gid] = f"Gruppo {gid}"

        _LOGGER.info("EW-50E: discovery completata, %d gruppi: %s", len(group_names), group_names)
        return group_names

    async def fetch_all_data(self) -> dict[str, Any]:
        await self._ensure_connected()
        # Richiedi ogni gruppo singolarmente (stato + eventuali errori)
        for gid in range(1, 18):
            await self.send_request(f'<?xml version="1.0" encoding="UTF-8"?><Packet><Command>getRequest</Command><DatabaseManager><Mnet Group="{gid}" Attribute="All"/></DatabaseManager></Packet>')
            await asyncio.sleep(0.1)
        await self.send_request(self._xml_get_alarm_list())
        await self.send_request(self._xml_get_system_alarm())
        await asyncio.sleep(1)
        messages = await self.receive_messages(timeout=8.0)
        return self._parse_messages(messages)

    def _parse_messages(self, messages: list[ET.Element]) -> dict[str, Any]:
        data: dict[str, Any] = {
            "groups": {}, "alarms": [], "system_alarm": {},
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
                    # Solo attributi di stato/anomalia: niente SetTemp/InletTemp
                    for attr in ["Drive", "Mode", "AirDirection",
                                 "FanSpeed", "ErrorSign", "ErrorCode", "GroupName"]:
                        val = mnet.get(attr)
                        if val is not None:
                            g[attr.lower()] = val
            for ref in db.findall("RefUnit"):
                if ref.get("ErrorSign") == "ON":
                    ec = ref.get("ErrorCode", "")
                    if ec:
                        data["alarms"].append({
                            "group": "",
                            "address": ref.get("Address", ""),
                            "error_code": ec,
                            "error_level": ref.get("ErrorLevel", ""),
                            "error_type": "RefUnit",
                        })
        return data


class EW50ECoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: EW50EClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.group_names: dict[str, str] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with async_timeout.timeout(60):
                if not self.group_names:
                    self.group_names = await self.client.discover_groups()
                    _LOGGER.info("EW-50E: gruppi attivi: %s", self.group_names)

                data = await self.client.fetch_all_data()

                for gid in list(data["groups"].keys()) + list(self.group_names.keys()):
                    if gid not in data["groups"]:
                        data["groups"][gid] = {}
                    g = data["groups"][gid]
                    if not g.get("groupname") and gid in self.group_names:
                        g["groupname"] = self.group_names[gid]
                    if not g.get("groupname"):
                        g["groupname"] = KNOWN_GROUP_NAMES.get(gid, f"Gruppo {gid}")

                return data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Errore connessione: {err}") from err
        except asyncio.TimeoutError:
            raise UpdateFailed("Timeout connessione")
        except Exception as err:
            _LOGGER.exception("Errore imprevisto EW-50E")
            raise UpdateFailed(f"Errore: {err}") from err
