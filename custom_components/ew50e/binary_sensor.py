"""Binary sensor per EW-50E — allarmi e anomalie di sistema e per singola zona."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
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
    """Configura i binary sensor di sistema e di zona per l'EW-50E."""
    coordinator: EW50ECoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [
        EW50ESystemAlarmBinarySensor(coordinator, entry),
        EW50ERefLeakBinarySensor(coordinator, entry),
    ]

    for group_id, group_name in coordinator.group_names.items():
        entities.append(
            EW50EGroupAlarmBinarySensor(coordinator, entry, group_id, group_name)
        )

    async_add_entities(entities)


class _Base(CoordinatorEntity[EW50ECoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = hub_device_info(entry.data["host"])

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class EW50ESystemAlarmBinarySensor(_Base):
    _attr_name = "Anomalia Sistema"
    _attr_unique_id = "ew50e_system_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        alarms = self.coordinator.data.get("alarms", [])
        sys_alarm = self.coordinator.data.get("system_alarm", {})
        return len(alarms) > 0 or sys_alarm.get("alert") == "ON"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarms = self.coordinator.data.get("alarms", [])
        sys_alarm = self.coordinator.data.get("system_alarm", {})
        return {
            "numero_allarmi": len(alarms),
            "alert_sistema": sys_alarm.get("alert", "OFF"),
            "codice_errore_sistema": sys_alarm.get("error_code", "0000"),
            "livello_alert": sys_alarm.get("alert_level", "0"),
            "stato_mnet": self.coordinator.data.get("mnet_status", "NORMAL"),
        }

    @property
    def icon(self) -> str:
        return "mdi:shield-alert" if self.is_on else "mdi:shield-check"


class EW50ERefLeakBinarySensor(_Base):
    _attr_name = "Perdita Gas Refrigerante"
    _attr_unique_id = "ew50e_ref_leak"
    _attr_device_class = BinarySensorDeviceClass.GAS
    _attr_icon = "mdi:molecule"

    @property
    def is_on(self) -> bool:
        sys_alarm = self.coordinator.data.get("system_alarm", {})
        return sys_alarm.get("ref_leak_alarm") == "ON"


class EW50EGroupAlarmBinarySensor(_Base):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

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
        self._attr_unique_id = f"ew50e_group_{group_id}_alarm"
        self._attr_name = "Anomalia"

    @property
    def is_on(self) -> bool:
        groups = self.coordinator.data.get("groups", {})
        group = groups.get(self._group_id, {})
        if (group.get("errorsign") or "").upper() in ("ON", "1"):
            return True
        alarms = self.coordinator.data.get("alarms", [])
        return any(str(a.get("group", "")) == self._group_id for a in alarms)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        groups = self.coordinator.data.get("groups", {})
        group = groups.get(self._group_id, {})
        alarms = self.coordinator.data.get("alarms", [])
        group_alarms = [
            a for a in alarms if str(a.get("group", "")) == self._group_id
        ]
        return {
            "gruppo_id": self._group_id,
            "nome": self._group_name,
            "nome_breve": self._nome_breve,
            "macro_zona": self._macro_zona,
            "error_sign": group.get("errorsign", "OFF"),
            "codice_errore": group.get("errorcode", ""),
            "dettaglio_allarmi": group_alarms,
        }

    @property
    def icon(self) -> str:
        return "mdi:alert" if self.is_on else "mdi:check-circle-outline"
