"""EW-50E Mitsubishi Electric - Custom Integration per Home Assistant.

Versione semplificata: monitora solo stati e anomalie.
Non legge più temperature (esterna/ingresso) né setpoint.
"""
from __future__ import annotations

import asyncio
import html
import logging
import ssl
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ew50e"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
SCAN_INTERVAL = timedelta(seconds=30)
WS_SUBPROTOCOL = "b_xmlproc"

# Attributi M-NET richiesti per ogni gruppo (sintassi wildcard EW-50E / AE-200)
MNET_STATE_ATTRS: tuple[str, ...] = (
    "Drive",
    "Mode",
    "AirDirection",
    "FanSpeed",
    "ErrorSign",
    "FilterSign",
)

# Attributi SystemAlarm richiesti al FreezerServlet dell'EW-50E
SYSTEM_ALARM_ATTRS: tuple[str, ...] = (
    "Alert",
    "AlertTriggerLevel",
    "AlertTriggerAddress",
    "AlertTriggerErrorCode",
    "BuzzerLamp",
    "BuzzerLampTriggerLevel",
    "BuzzerLampTriggerAddress",
    "BuzzerLampTriggerErrorCode",
    "BuzzerLampTriggerErrorInfo",
    "RefLeakAddress",
    "RefLeakAlarm",
    "RefLeakAlarmCode",
    "RefLeakAlarmLevel",
    "RefLeakAlarmType",
)

# Nomi gruppi configurati sull'EW-50E (fallback se GroupNameWeb è vuoto)
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


class EW50EAuthError(Exception):
    """Errore di autenticazione verso EW-50E."""


def _make_ssl_context() -> ssl.SSLContext:
    """Crea un contesto SSL leggero per certificato self-signed senza bloccare l'event loop."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def parse_zone_metadata(group_name: str) -> tuple[str, str]:
    """Estrae (macro_zona, nome_breve) dal nome completo del gruppo EW-50E."""
    clean = group_name.strip()
    low = clean.lower()
    if low.startswith("farmacia") and "-" in clean:
        return "Farmacia", clean.split("-", 1)[1].strip()
    if low.startswith("casa") and "-" in clean:
        return "Casa", clean.split("-", 1)[1].strip()
    if low.startswith("bilocale") and "-" in clean:
        return "Bilocale", clean.split("-", 1)[1].strip()
    if (low.startswith("studi ") or low.startswith("studi-")) and "-" in clean:
        return "Studi", clean.split("-", 1)[1].strip()
    if low.startswith(("studio", "studi")):
        return "Studi", clean
    if "-" in clean:
        parts = clean.split("-", 1)
        return parts[0].strip(), parts[1].strip()
    return "Altro", clean


def hub_device_info(host: str) -> DeviceInfo:
    """DeviceInfo del controller centrale EW-50E (contiene solo le 4 entità globali)."""
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        name="EW50E",
        manufacturer="Mitsubishi Electric",
        model="EW-50E / EW-C50E (Controller Centrale)",
        configuration_url=f"https://{host}/control/",
    )


def zone_device_info(host: str, group_id: str, group_name: str) -> DeviceInfo:
    """DeviceInfo dedicato per singola zona M-NET (contiene Stato e Anomalia della zona)."""
    macro_zona, _ = parse_zone_metadata(group_name)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{host}_group_{group_id}")},
        via_device=(DOMAIN, host),
        name=group_name,
        manufacturer="Mitsubishi Electric",
        model=f"Zona M-NET #{group_id} ({macro_zona})",
        configuration_url=f"https://{host}/control/",
    )


def _build_canonical_entity_ids(group_names: dict[str, str]) -> dict[str, str]:
    """Mappa unique_id -> entity_id pulito (senza prefissi di Area o nome Hub)."""
    mapping: dict[str, str] = {
        "ew50e_system_alarm": "sensor.ew50e_stato_sistema",
        "ew50e_alarm_count": "sensor.ew50e_allarmi_attivi",
        "ew50e_system_problem": "binary_sensor.ew50e_anomalia_sistema",
        "ew50e_ref_leak": "binary_sensor.ew50e_perdita_gas_refrigerante",
    }
    for gid, gname in group_names.items():
        slug = slugify(gname) or f"gruppo_{gid}"
        mapping[f"ew50e_group_{gid}_status"] = f"sensor.{slug}_stato"
        mapping[f"ew50e_group_{gid}_alarm"] = f"binary_sensor.{slug}_anomalia"
    return mapping


async def _async_prepare_devices_and_migrate(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: EW50ECoordinator
) -> None:
    """Assicura i dispositivi per zona e migra eventuali entità preesistenti dal vecchio hub unico."""
    host = entry.data[CONF_HOST]
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    hub_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name="EW50E",
        manufacturer="Mitsubishi Electric",
        model="EW-50E / EW-C50E (Controller Centrale)",
        configuration_url=f"https://{host}/control/",
    )
    if hub_dev.name == "EW-50E Mitsubishi" and hub_dev.name_by_user is None:
        dev_reg.async_update_device(hub_dev.id, name="EW50E")

    zone_dev_ids: dict[str, str] = {}
    for gid, gname in coordinator.group_names.items():
        macro_zona, _ = parse_zone_metadata(gname)
        zdev = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{host}_group_{gid}")},
            via_device_id=hub_dev.id,
            name=gname,
            manufacturer="Mitsubishi Electric",
            model=f"Zona M-NET #{gid} ({macro_zona})",
            configuration_url=f"https://{host}/control/",
        )
        zone_dev_ids[gid] = zdev.id

    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = reg_entry.unique_id or ""
        if uid.startswith("ew50e_group_"):
            parts = uid.split("_")
            # Formato: ew50e_group_<gid>_status | ew50e_group_<gid>_alarm
            if len(parts) >= 4:
                gid = parts[2]
                target_dev_id = zone_dev_ids.get(gid)
                if target_dev_id and reg_entry.device_id != target_dev_id:
                    ent_reg.async_update_entity(reg_entry.entity_id, device_id=target_dev_id)


async def _async_normalize_entity_ids(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: EW50ECoordinator
) -> None:
    """Rimuove prefissi indesiderati (es. area 'cortile_ew_50e_mitsubishi_') dagli entity_id."""
    ent_reg = er.async_get(hass)
    canonical = _build_canonical_entity_ids(coordinator.group_names)

    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        target_id = canonical.get(reg_entry.unique_id or "")
        if target_id and reg_entry.entity_id != target_id:
            try:
                ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=target_id)
                _LOGGER.info(
                    "EW-50E: entity_id normalizzato %s -> %s",
                    reg_entry.entity_id,
                    target_id,
                )
            except ValueError as err:
                _LOGGER.debug(
                    "EW-50E: impossibile rinominare %s in %s (%s)",
                    reg_entry.entity_id,
                    target_id,
                    err,
                )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'integrazione EW-50E da una ConfigEntry."""
    client = EW50EClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = EW50ECoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await _async_prepare_devices_and_migrate(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_normalize_entity_ids(hass, entry, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica la ConfigEntry e chiude le connessioni aperte."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: EW50ECoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.disconnect()
    return unload_ok


class EW50EClient:
    """Client asincrono HTTPS + WebSocket XML (b_xmlproc) per Mitsubishi EW-50E / EW-C50E."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self._token: str | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ssl_ctx: ssl.SSLContext | None = None
        self._lock = asyncio.Lock()
        self._first_connect_logged: bool = False
        # Cache cumulativa per preservare stati aggiornati anche via notifyRequest
        self._cached_state: dict[str, Any] = {
            "groups": {},
            "alarms": [],
            "system_alarm": {},
            "mnet_status": "NORMAL",
        }

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
        """Effettua il login Basic Auth su /servlet/Login e ottiene il Bearer token."""
        _LOGGER.debug("EW-50E: login su %s...", self.host)
        session = self._get_session()
        url = f"https://{self.host}/servlet/Login"
        auth = aiohttp.BasicAuth(self.username, self.password)
        headers = {"Content-Type": "text/plain"}
        async with asyncio.timeout(10):
            async with session.get(url, auth=auth, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise EW50EAuthError(
                        f"Credenziali non valide per {self.host} (HTTP {resp.status})"
                    )
                if resp.status != 200:
                    raise ValueError(f"Login fallito su {self.host}, HTTP {resp.status}")
                token = (await resp.text()).strip()
                if not token:
                    raise EW50EAuthError("Token vuoto ricevuto da /servlet/Login")
                self._token = token
                return True

    async def refresh_token(self) -> bool:
        """Rinnova il token di accesso tramite /servlet/Update (fallback su login completo)."""
        if not self._token:
            return await self.login()
        session = self._get_session()
        url = f"https://{self.host}/servlet/Update"
        headers = {
            "Content-Type": "text/plain",
            "Authorization": f"Bearer {self._token}",
        }
        try:
            async with asyncio.timeout(10):
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        new_token = (await resp.text()).strip()
                        if new_token:
                            self._token = new_token
                            return True
        except (aiohttp.ClientError, TimeoutError):
            pass
        self._token = None
        return await self.login()

    async def connect(self) -> None:
        """Apre il WebSocket autenticato su wss://<host>/b_xmlproc/?token=... con subprotocol b_xmlproc."""
        if not self._token:
            await self.login()
        session = self._get_session()
        ws_url = f"wss://{self.host}/b_xmlproc/?token={self._token}"
        headers = {"Origin": f"https://{self.host}"}
        try:
            async with asyncio.timeout(10):
                self._ws = await session.ws_connect(
                    ws_url,
                    ssl=self._get_ssl_ctx(),
                    protocols=(WS_SUBPROTOCOL,),
                    headers=headers,
                    heartbeat=25,
                )
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                # Il token potrebbe essere scaduto: rinnova e riprova una volta
                _LOGGER.debug("EW-50E: token WS scaduto (HTTP %s), rinnovo login...", err.status)
                self._token = None
                await self.login()
                ws_url = f"wss://{self.host}/b_xmlproc/?token={self._token}"
                async with asyncio.timeout(10):
                    self._ws = await session.ws_connect(
                        ws_url,
                        ssl=self._get_ssl_ctx(),
                        protocols=(WS_SUBPROTOCOL,),
                        headers=headers,
                        heartbeat=25,
                    )
            else:
                raise

        if not self._first_connect_logged:
            _LOGGER.info("EW-50E: connesso via WebSocket (b_xmlproc) a %s", self.host)
            self._first_connect_logged = True
        else:
            _LOGGER.debug("EW-50E: WebSocket riconnesso a %s", self.host)

        # Invia l'handshake MnetStatus come fa l'interfaccia web ufficiale all'apertura
        await self._send_and_wait_get_response(self._xml_get_mnet_status(), timeout=6.0)

    async def disconnect(self) -> None:
        """Chiude il WebSocket e la sessione HTTP."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _ensure_connected(self) -> None:
        if self._ws is None or self._ws.closed:
            await self.connect()

    def _strip_http_envelope(self, raw: str) -> str:
        """Rimuove eventuali intestazioni HTTP preposte dal controller prima di <?xml o <Packet>."""
        idx = raw.find("<?xml")
        if idx == -1:
            idx = raw.find("<Packet")
        return raw[idx:] if idx > 0 else raw

    async def _send_and_wait_get_response(
        self, payload: str, timeout: float = 8.0
    ) -> list[ET.Element]:
        """Invia un comando XML e raccoglie i pacchetti (inclusi notifyRequest) fino al getResponse."""
        await self._ensure_connected()
        assert self._ws is not None
        await self._ws.send_str(payload)

        collected: list[ET.Element] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0 or self._ws is None:
                break
            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
            except TimeoutError:
                _LOGGER.debug("EW-50E: timeout in attesa di getResponse (%.1fs)", timeout)
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                xml_str = self._strip_http_envelope(msg.data)
                try:
                    root = ET.fromstring(xml_str)
                except ET.ParseError as err:
                    _LOGGER.debug("EW-50E: XML non valido ignorato (%s): %.120r", err, msg.data)
                    continue

                collected.append(root)
                cmd = (root.findtext("Command") or "").strip()
                if cmd in ("getResponse", "getErrorResponse", "setResponse", "setErrorResponse"):
                    break
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                _LOGGER.debug("EW-50E: WebSocket chiuso durante ricezione (%s)", msg.type)
                self._ws = None
                break

        return collected

    async def _drain_notifications(self, timeout: float = 0.25) -> list[ET.Element]:
        """Legge eventuali notifyRequest spontanei già presenti nel buffer del WebSocket."""
        if self._ws is None or self._ws.closed:
            return []
        collected: list[ET.Element] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0 or self._ws is None:
                break
            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
            except TimeoutError:
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                xml_str = self._strip_http_envelope(msg.data)
                try:
                    collected.append(ET.fromstring(xml_str))
                except ET.ParseError:
                    continue
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                self._ws = None
                break
        return collected

    # ------------------------------------------------------------------
    # Costruttori XML ufficiali Mitsubishi EW-50E (estratti da main.js)
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_packet(inner_xml: str, servlet_header: str | None = None) -> str:
        prefix = f"{servlet_header}\r\n\r\n" if servlet_header else ""
        return (
            f"{prefix}"
            '<?xml version="1.0" encoding="UTF-8" ?>\r\n'
            "<Packet>\r\n"
            "<Command>getRequest</Command>\r\n"
            "<DatabaseManager>\r\n"
            f"{inner_xml}"
            "</DatabaseManager>\r\n"
            "</Packet>"
        )

    def _xml_get_mnet_status(self) -> str:
        return self._wrap_packet('<SystemData MnetStatus="*" />\r\n')

    def _xml_get_group_list(self) -> str:
        return self._wrap_packet("<ControlGroup>\r\n<MnetList />\r\n</ControlGroup>\r\n")

    def _xml_get_groups_state(self, group_ids: list[str]) -> str:
        attrs = " ".join(f'{attr}="*"' for attr in MNET_STATE_ATTRS)
        lines = "".join(
            f'<Mnet Group="{html.escape(gid, quote=True)}" {attrs} />\r\n'
            for gid in group_ids
        )
        return self._wrap_packet(lines)

    def _xml_get_alarm_list(self) -> str:
        return self._wrap_packet("<Mnet>\r\n<AlarmStatusList />\r\n</Mnet>\r\n")

    def _xml_get_system_alarm(self) -> str:
        attrs = " ".join(f'{attr}="*"' for attr in SYSTEM_ALARM_ATTRS)
        return self._wrap_packet(
            f"<SystemAlarm {attrs} />\r\n",
            servlet_header="POST /servlet/FreezerServlet HTTP/1.1",
        )

    # ------------------------------------------------------------------
    # Operazioni ad alto livello
    # ------------------------------------------------------------------

    async def discover_groups(self) -> dict[str, str]:
        """Scopre i gruppi configurati e i relativi GroupNameWeb tramite ControlGroup/MnetList."""
        async with self._lock:
            packets = await self._send_and_wait_get_response(
                self._xml_get_group_list(), timeout=10.0
            )
            # Aggiorna subito eventuali notify ricevuti nel frattempo
            self._apply_packets_to_cache(packets)

            discovered: dict[str, str] = {}
            for packet in packets:
                for rec in packet.findall(".//ControlGroup/MnetList/MnetRecord"):
                    gid = (rec.get("Group") or "").strip()
                    if not gid:
                        continue
                    web_name = (rec.get("GroupNameWeb") or rec.get("GroupName") or "").strip()
                    discovered[gid] = web_name

            all_groups = set(discovered.keys()) if discovered else set(KNOWN_GROUP_NAMES.keys())

            group_names: dict[str, str] = {}
            for gid in sorted(all_groups, key=lambda x: int(x) if x.isdigit() else 0):
                web_name = discovered.get(gid, "")
                known_name = KNOWN_GROUP_NAMES.get(gid, "")
                if web_name and known_name:
                    norm_web = web_name.replace(" ", "").lower()
                    norm_known = known_name.replace(" ", "").lower()
                    # L'hardware EW-50E tronca GroupNameWeb a 20 caratteri:
                    # se il nome letto è il prefisso troncato del nome noto, ripristina la dicitura completa
                    if norm_known.startswith(norm_web):
                        group_names[gid] = known_name
                    else:
                        group_names[gid] = web_name
                elif web_name:
                    group_names[gid] = web_name
                elif known_name:
                    group_names[gid] = known_name
                else:
                    group_names[gid] = f"Gruppo {gid}"

            _LOGGER.info(
                "EW-50E: discovery completata (%d gruppi rilevati dal controller)",
                len(group_names),
            )
            _LOGGER.debug("EW-50E: mappa gruppi = %s", group_names)
            return group_names

    async def fetch_all_data(self, group_ids: list[str] | None = None) -> dict[str, Any]:
        """Esegue il polling sequenziale ordinato di MnetStatus, Gruppi, AlarmStatusList e SystemAlarm."""
        async with self._lock:
            target_groups = group_ids if group_ids else list(KNOWN_GROUP_NAMES.keys())
            packets: list[ET.Element] = []

            # 1. Drena eventuali notify spontanei arrivati tra un ciclo e l'altro
            packets.extend(await self._drain_notifications(timeout=0.2))

            # 2. Stato globale M-NET
            packets.extend(
                await self._send_and_wait_get_response(self._xml_get_mnet_status(), timeout=6.0)
            )

            # 3. Stato di tutti i gruppi (singola richiesta batch; fallback per-gruppo se vuoto)
            group_packets = await self._send_and_wait_get_response(
                self._xml_get_groups_state(target_groups), timeout=10.0
            )
            packets.extend(group_packets)

            # Verifica se la risposta batch conteneva tag <Mnet Group="...">
            has_mnet = any(
                p.find(".//DatabaseManager/Mnet") is not None for p in group_packets
            )
            if not has_mnet:
                _LOGGER.debug("EW-50E: risposta batch vuota, interrogo i gruppi singolarmente")
                for gid in target_groups:
                    packets.extend(
                        await self._send_and_wait_get_response(
                            self._xml_get_groups_state([gid]), timeout=5.0
                        )
                    )

            # 4. Lista allarmi M-NET (AlarmStatusList)
            alarm_packets = await self._send_and_wait_get_response(
                self._xml_get_alarm_list(), timeout=8.0
            )
            packets.extend(alarm_packets)

            # 5. Allarme globale di sistema / perdita gas (FreezerServlet -> SystemAlarm)
            sys_alarm_packets = await self._send_and_wait_get_response(
                self._xml_get_system_alarm(), timeout=6.0
            )
            # Se FreezerServlet restituisce errore o vuoto su modelli senza modulo Freezer,
            # proviamo anche senza l'header FreezerServlet
            has_sys_alarm = any(
                p.find(".//DatabaseManager/SystemAlarm") is not None for p in sys_alarm_packets
            )
            if not has_sys_alarm:
                attrs = " ".join(f'{attr}="*"' for attr in SYSTEM_ALARM_ATTRS)
                fallback_xml = self._wrap_packet(f"<SystemAlarm {attrs} />\r\n")
                sys_alarm_packets.extend(
                    await self._send_and_wait_get_response(fallback_xml, timeout=5.0)
                )
            packets.extend(sys_alarm_packets)

            self._apply_packets_to_cache(packets)
            return {
                "groups": {k: dict(v) for k, v in self._cached_state["groups"].items()},
                "alarms": list(self._cached_state["alarms"]),
                "system_alarm": dict(self._cached_state["system_alarm"]),
                "mnet_status": self._cached_state["mnet_status"],
            }

    def _apply_packets_to_cache(self, messages: list[ET.Element]) -> None:
        """Aggiorna lo stato cumulativo dai pacchetti XML ricevuti (getResponse e notifyRequest)."""
        alarm_codes_by_group: dict[str, str] = {}

        for packet in messages:
            db = packet.find("DatabaseManager")
            if db is None:
                continue

            sys_data = db.find("SystemData")
            if sys_data is not None:
                mnet_st = sys_data.get("MnetStatus")
                if mnet_st and mnet_st != "*":
                    self._cached_state["mnet_status"] = mnet_st

            sys_alarm = db.find("SystemAlarm")
            if sys_alarm is not None:
                def _clean(val: str | None, default: str) -> str:
                    return default if val in (None, "", "*") else val

                self._cached_state["system_alarm"] = {
                    "alert": _clean(sys_alarm.get("Alert"), "OFF"),
                    "alert_level": _clean(sys_alarm.get("AlertTriggerLevel"), "0"),
                    "alert_address": _clean(sys_alarm.get("AlertTriggerAddress"), "0"),
                    "error_code": _clean(sys_alarm.get("AlertTriggerErrorCode"), "0000"),
                    "buzzer_lamp": _clean(sys_alarm.get("BuzzerLamp"), "OFF"),
                    "ref_leak_alarm": _clean(sys_alarm.get("RefLeakAlarm"), "OFF"),
                }

            alarm_list = db.find(".//AlarmStatusList")
            if alarm_list is not None:
                # Sostituisce la lista allarmi corrente con lo snapshot aggiornato dal controller
                new_alarms: list[dict[str, str]] = []
                for alarm in alarm_list.findall("AlarmStatusRecord"):
                    grp = (alarm.get("Group") or "").strip()
                    code = (
                        alarm.get("AlarmCode")
                        or alarm.get("ErrorCode")
                        or ""
                    ).strip()
                    new_alarms.append({
                        "group": grp,
                        "address": (alarm.get("Address") or "").strip(),
                        "error_code": code,
                        "error_level": (alarm.get("ErrorLevel") or "").strip(),
                        "error_type": (
                            alarm.get("Model") or alarm.get("ErrorType") or ""
                        ).strip(),
                        "group_name_web": (alarm.get("GroupNameWeb") or "").strip(),
                    })
                    if grp and code:
                        alarm_codes_by_group[grp] = code
                self._cached_state["alarms"] = new_alarms

            for mnet in db.findall("Mnet"):
                group = (mnet.get("Group") or "").strip()
                if not group:
                    continue
                attrs = {k: v for k, v in mnet.attrib.items() if k != "Group"}
                # Ignora i gruppi non configurati che rimandano indietro solo "*"
                if attrs and all(v == "*" for v in attrs.values()):
                    continue

                g = self._cached_state["groups"].setdefault(group, {})
                for attr in (
                    "Drive",
                    "Mode",
                    "AirDirection",
                    "FanSpeed",
                    "ErrorSign",
                    "FilterSign",
                    "ErrorCode",
                    "AlarmCode",
                    "GroupName",
                    "GroupNameWeb",
                ):
                    val = mnet.get(attr)
                    if val is not None and val != "*":
                        g[attr.lower()] = val

            for ref in db.findall("RefUnit"):
                if ref.get("ErrorSign") in ("ON", "1"):
                    ec = (ref.get("ErrorCode") or ref.get("AlarmCode") or "").strip()
                    if ec:
                        self._cached_state["alarms"].append({
                            "group": "",
                            "address": (ref.get("Address") or "").strip(),
                            "error_code": ec,
                            "error_level": (ref.get("ErrorLevel") or "").strip(),
                            "error_type": "RefUnit",
                        })

        # Sincronizza codice errore sui singoli gruppi dalla AlarmStatusList
        for gid, g in self._cached_state["groups"].items():
            if gid in alarm_codes_by_group:
                g["errorcode"] = alarm_codes_by_group[gid]
            elif g.get("errorsign") in ("OFF", "0", "", None):
                g["errorcode"] = ""


class EW50ECoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator per l'aggiornamento periodico dei dati dall'EW-50E."""

    def __init__(self, hass: HomeAssistant, client: EW50EClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.group_names: dict[str, str] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(60):
                if not self.group_names:
                    self.group_names = await self.client.discover_groups()

                data = await self.client.fetch_all_data(list(self.group_names.keys()))

                for gid in list(data["groups"].keys()) + list(self.group_names.keys()):
                    if gid not in data["groups"]:
                        data["groups"][gid] = {}
                    g = data["groups"][gid]
                    if not g.get("groupname") and gid in self.group_names:
                        g["groupname"] = self.group_names[gid]
                    if not g.get("groupname"):
                        g["groupname"] = KNOWN_GROUP_NAMES.get(gid, f"Gruppo {gid}")

                return data

        except EW50EAuthError as err:
            raise UpdateFailed(f"Autenticazione EW-50E fallita: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Errore connessione EW-50E ({self.client.host}): {err}") from err
        except TimeoutError as err:
            raise UpdateFailed(f"Timeout connessione EW-50E ({self.client.host})") from err
        except Exception as err:
            _LOGGER.error("Errore durante l'aggiornamento EW-50E: %s", err)
            raise UpdateFailed(f"Errore EW-50E: {err}") from err
