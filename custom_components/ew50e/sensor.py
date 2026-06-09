"""Sensori per EW-50E Mitsubishi Electric."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, EW50ECoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EW50ECoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    entities.append(EW50EOutdoorTempSensor(coordinator, entry))
    entities.append(EW50ESystemAlarmSensor(coordinator, entry))
    entities.append(EW50EAlarmCountSensor(coordinator, entry))

    for group_id, group_name in coordinator.group_names.items():
        entities.append(EW50EGroupInletTempSensor(coordinator, entry, group_id, group_name))
        entities.append(EW50EGroupSetTempSensor(coordinator, entry, group_id, group_name))
        entities.append(EW50EGroupStatusSensor(coordinator, entry, group_id, group_name))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data["host"])},
        name="EW-50E Mitsubishi",
        manufacturer="Mitsubishi Electric",
        model="EW-C50E",
        configuration_url=f"https://{entry.data['host']}/control/",
    )


class _Base(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class EW50EOutdoorTempSensor(_Base):
    _attr_name = "EW-50E Temperatura Esterna"
    _attr_unique_id = "ew50e_outdoor_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("outdoor_temp")


class EW50ESystemAlarmSensor(_Base):
    _attr_name = "EW-50E Stato Sistema"
    _attr_unique_id = "ew50e_system_alarm"

    @property
    def native_value(self) -> str:
        alarm = self.coordinator.data.get("system_alarm", {})
        if alarm.get("alert") == "ON":
            return "ALLARME"
        mnet = self.coordinator.data.get("mnet_status", "UNKNOWN")
        return "NORMALE" if mnet == "NORMAL" else mnet

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
            "stato_mnet": self.coordinator.data.get("mnet_status", "UNKNOWN"),
        }

    @property
    def icon(self) -> str:
        alarm = self.coordinator.data.get("system_alarm", {})
        return "mdi:shield-alert" if alarm.get("alert") == "ON" else "mdi:shield-check"


class EW50EAlarmCountSensor(_Base):
    _attr_name = "EW-50E Allarmi Attivi"
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
            name = self.coordinator.group_names.get(gid, f"Gruppo {gid}" if gid else "Sistema")
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
    def __init__(self, coordinator, entry, group_id, group_name):
        super().__init__(coordinator, entry)
        self._group_id = group_id
        self._group_name = group_name

    def _group_data(self) -> dict[str, Any]:
        return self.coordinator.data.get("groups", {}).get(self._group_id, {})


class EW50EGroupInletTempSensor(_GroupBase):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry, group_id, group_name):
        super().__init__(coordinator, entry, group_id, group_name)
        self._attr_unique_id = f"ew50e_group_{group_id}_inlet_temp"
        self._attr_name = f"{group_name} - Temperatura"

    @property
    def native_value(self) -> float | None:
        val = self._group_data().get("inlettemp")
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        g = self._group_data()
        return {
            "gruppo_id": self._group_id,
            "drive": g.get("drive", ""),
            "modalita": g.get("mode", ""),
        }


class EW50EGroupSetTempSensor(_GroupBase):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, coordinator, entry, group_id, group_name):
        super().__init__(coordinator, entry, group_id, group_name)
        self._attr_unique_id = f"ew50e_group_{group_id}_set_temp"
        self._attr_name = f"{group_name} - Setpoint"

    @property
    def native_value(self) -> float | None:
        val = self._group_data().get("settemp")
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None


class EW50EGroupStatusSensor(_GroupBase):
    def __init__(self, coordinator, entry, group_id, group_name):
        super().__init__(coordinator, entry, group_id, group_name)
        self._attr_unique_id = f"ew50e_group_{group_id}_status"
        self._attr_name = f"{group_name} - Stato"

    @property
    def native_value(self) -> str:
        g = self._group_data()
        if g.get("errorsign") == "ON":
            return "ERRORE"
        drive = g.get("drive", "")
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
        group_alarms = [a for a in alarms if str(a.get("group", "")) == self._group_id]
        return {
            "gruppo_id": self._group_id,
            "drive": g.get("drive", ""),
            "modalita": g.get("mode", ""),
            "velocita_fan": g.get("fanspeed", ""),
            "direzione_aria": g.get("airdirection", ""),
            "errore": g.get("errorsign", "OFF"),
            "codice_errore": g.get("errorcode", ""),
            "allarmi_attivi": group_alarms,
        }

    @property
    def icon(self) -> str:
        val = self.native_value or ""
        return "mdi:alert" if "ERRORE" in val else "mdi:air-conditioner"
