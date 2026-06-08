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
    """Setup sensori EW-50E."""
    coordinator: EW50ECoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    entities.append(EW50EOutdoorTempSensor(coordinator, entry))
    entities.append(EW50ESystemAlarmSensor(coordinator, entry))
    entities.append(EW50EAlarmCountSensor(coordinator, entry))

    for group_id, group_name in coordinator.group_names.items():
        entities.append(EW50EGroupInletTempSensor(coordinator, entry, group_id, group_name))
        entities.append(EW50EGroupStatusSensor(coordinator, entry, group_id, group_name))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="EW-50E",
        manufacturer="Mitsubishi Electric",
        model="EW-50E / EW-C50E",
    )


class EW50EOutdoorTempSensor(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    """Sensore temperatura esterna."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_outdoor_temp"
        self._attr_name = "Temperatura Esterna"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("system", {}).get("outdoor_temp")


class EW50ESystemAlarmSensor(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    """Sensore stato sistema M-NET."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_system_status"
        self._attr_name = "Stato Sistema"
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("system", {}).get("status", "N/D")


class EW50EAlarmCountSensor(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    """Contatore allarmi attivi."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_alarm_count"
        self._attr_name = "Allarmi Attivi"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get("system", {}).get("alarm_count", 0)


class EW50EGroupInletTempSensor(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    """Sensore temperatura di ritorno (Inlet) del gruppo."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry, group_id: str, group_name: str) -> None:
        super().__init__(coordinator, entry)
        self._group_id = group_id
        self._group_name = group_name
        self._attr_unique_id = f"{entry.entry_id}_group_{group_id}_temp"
        self._attr_name = f"{group_name} Temperatura"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        groups = self.coordinator.data.get("groups", {})
        return groups.get(self._group_id, {}).get("temp")


class EW50EGroupStatusSensor(CoordinatorEntity[EW50ECoordinator], SensorEntity):
    """Sensore stato operativo del gruppo (Stato e Modalità)."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry, group_id: str, group_name: str) -> None:
        super().__init__(coordinator, entry)
        self._group_id = group_id
        self._group_name = group_name
        self._attr_unique_id = f"{entry.entry_id}_group_{group_id}_status"
        self._attr_name = f"{group_name} Stato Operativo"
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> str:
        groups = self.coordinator.data.get("groups", {})
        group = groups.get(self._group_id, {})
        if group.get("errorsign") == "ON":
            return "ERRORE"
        if group.get("drive") == "ON":
            mode = group.get("mode", "")
            return f"ON - {mode}" if mode else "ON"
        return "OFF"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        groups = self.coordinator.data.get("groups", {})
        group = groups.get(self._group_id, {})
        return {
            "gruppo": self._group_id,
            "nome": self._group_name,
            "drive": group.get("drive", ""),
            "modalita": group.get("mode", ""),
            "velocita_fan": group.get("fanspeed", ""),
            "direzione_aria": group.get("airdirection", ""),
            "codice_errore": group.get("errorcode", ""),
        }
