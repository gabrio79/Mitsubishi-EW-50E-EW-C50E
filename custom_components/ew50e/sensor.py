"""Sensori per EW-50E Mitsubishi Electric.

Versione semplificata: solo stati e anomalie (niente temperature/setpoint).
Ogni zona M-NET è associata al proprio sotto-dispositivo dedicato.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import (
    DOMAIN,
    EW50ECoordinator,
    hub_device_info,
    parse_zone_metadata,
    zone_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura i sensori di sistema e di zona per l'EW-50E."""
    coordinator: EW50ECoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        EW50ESystemAlarmSensor(coordinator, entry),
        EW50EAlarmCountSensor(coordinator, entry),
    ]

    for group_id, group_name in coordinator.group_names.items():
        entities.append(
            EW50EGroupStatusSensor(coordinator, entry, group_id, group_name)
        )

    async_add_entities(entities)


class _Base(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = hub_device_info(entry.data["host"])

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class EW50ESystemAlarmSensor(_Base):
    _attr_name = "Stato Sistema"
    _attr_unique_id = "ew50e_system_alarm"

    @property
    def native_value(self) -> str:
        alarm = self.coordinator.data.get("system_alarm", {})
        if alarm.get("alert") == "ON":
            return "ALLARME"
        mnet = self.coordinator.data.get("mnet_status", "NORMAL")
        return "NORMALE" if mnet in ("NORMAL", "UNKNOWN") else mnet

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = self.coordinator.data.get("system_alarm", {})
        return {
            "alert": alarm.get("alert", "OFF"),
            "livello_alert": alarm.get("alert_level", "0"),
            "indirizzo_trigger": alarm.get("alert_address", "0"),
            "codice_errore": alarm.get("error_code", "0000"),
            "buzzer_lampeggio": alarm.get("buzzer_lamp", "OFF"),
            "allarme_perdita_gas": alarm.get("ref_leak_alarm", "OFF"),
            "stato_mnet": self.coordinator.data.get("mnet_status", "NORMAL"),
        }

    @property
    def icon(self) -> str:
        alarm = self.coordinator.data.get("system_alarm", {})
        return "mdi:shield-alert" if alarm.get("alert") == "ON" else "mdi:shield-check"


class EW50EAlarmCountSensor(_Base):
    _attr_name = "Allarmi Attivi"
    _attr_unique_id = "ew50e_alarm_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("alarms", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarms = self.coordinator.data.get("alarms", [])
        result: dict[str, Any] = {}
        for i, alarm in enumerate(alarms):
            gid = str(alarm.get("group", ""))
            name = self.coordinator.group_names.get(
                gid, f"Gruppo {gid}" if gid else "Sistema"
            )
            result[f"allarme_{i + 1}"] = {
                "gruppo": gid,
                "nome": name,
                "indirizzo": alarm.get("address", ""),
                "codice_errore": alarm.get("error_code", ""),
                "livello": alarm.get("error_level", ""),
                "tipo": alarm.get("error_type", ""),
            }
        return result

    @property
    def icon(self) -> str:
        return "mdi:alert-circle" if (self.native_value or 0) > 0 else "mdi:check-circle"


class _GroupBase(_Base):
    def __init__(
        self,
        coordinator: EW50ECoordinator,
        entry: ConfigEntry,
        group_id: str,
        group_name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._group_id = group_id
        self._group_name = group_name
        self._macro_zona, self._nome_breve = parse_zone_metadata(group_name)
        self._attr_device_info = zone_device_info(
            entry.data["host"], group_id, group_name
        )

    def _group_data(self) -> dict[str, Any]:
        return self.coordinator.data.get("groups", {}).get(self._group_id, {})


class EW50EGroupStatusSensor(_GroupBase):
    def __init__(
        self,
        coordinator: EW50ECoordinator,
        entry: ConfigEntry,
        group_id: str,
        group_name: str,
    ) -> None:
        super().__init__(coordinator, entry, group_id, group_name)
        self._attr_unique_id = f"ew50e_group_{group_id}_status"
        self._attr_name = "Stato"

    @property
    def native_value(self) -> str:
        g = self._group_data()
        err_sign = (g.get("errorsign") or "").upper()
        if err_sign in ("ON", "1"):
            return "ERRORE"
        drive = (g.get("drive") or "").upper()
        if drive == "ON":
            mode = g.get("mode", "")
            return f"ON - {mode}" if mode else "ON"
        if drive == "OFF":
            return "OFF"
        return "N/D"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        g = self._group_data()
        alarms = self.coordinator.data.get("alarms", [])
        group_alarms = [
            a for a in alarms if str(a.get("group", "")) == self._group_id
        ]
        return {
            "gruppo_id": self._group_id,
            "nome": self._group_name,
            "nome_breve": self._nome_breve,
            "macro_zona": self._macro_zona,
            "drive": g.get("drive", ""),
            "modalita": g.get("mode", ""),
            "velocita_fan": g.get("fanspeed", ""),
            "direzione_aria": g.get("airdirection", ""),
            "errore": g.get("errorsign", "OFF"),
            "segnalazione_filtro": g.get("filtersign", "OFF"),
            "codice_errore": g.get("errorcode", ""),
            "allarmi_attivi": group_alarms,
        }

    @property
    def icon(self) -> str:
        val = self.native_value or ""
        return "mdi:alert" if "ERRORE" in val else "mdi:air-conditioner"
