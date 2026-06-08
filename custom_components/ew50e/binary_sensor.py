"""Binary sensor per EW-50E Mitsubishi Electric - Allarmi e anomalie."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Setup binary sensor EW-50E."""
    coordinator: EW50ECoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    entities.append(EW50ESystemAlarmBinarySensor(coordinator, entry))
    entities.append(EW50ERefLeakBinarySensor(coordinator, entry))

    for group_id, group_name in coordinator.group_names.items():
        entities.append(EW50EGroupAlarmBinarySensor(coordinator, entry, group_id, group_name))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="EW-50E",
        manufacturer="Mitsubishi Electric",
        model="EW-50E / EW-C50E",
    )


class EW50ESystemAlarmBinarySensor(CoordinatorEntity[EW50ECoordinator], BinarySensorEntity):
    """Allarme globale cumulativo di sistema."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_system_alarm"
        self._attr_name = "Anomalia Sistema"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("system", {}).get("status") == "ALLARME"


class EW50ERefLeakBinarySensor(CoordinatorEntity[EW50ECoordinator], BinarySensorEntity):
    """Allarme critico perdita gas refrigerante."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ref_leak"
        self._attr_name = "Perdita Gas Refrigerante"
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        alarms = self.coordinator.data.get("alarms", [])
        return any(a.get("type") == "leak" for a in alarms)


class EW50EGroupAlarmBinarySensor(CoordinatorEntity[EW50ECoordinator], BinarySensorEntity):
    """Allarme anomalia associato al singolo gruppo."""

    def __init__(self, coordinator: EW50ECoordinator, entry: ConfigEntry, group_id: str, group_name: str) -> None:
        super().__init__(coordinator, entry)
        self._group_id = group_id
        self._group_name = group_name
        self._attr_unique_id = f"{entry.entry_id}_group_{group_id}_alarm"
        self._attr_name = f"{group_name} Anomalia"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_device_info = _device_info(entry)
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        groups = self.coordinator.data.get("groups", {})
        if groups.get(self._group_id, {}).get("errorsign") == "ON":
            return True
        alarms = self.coordinator.data.get("alarms", [])
        return any(str(a.get("group", "")) == self._group_id for a in alarms)

    @property
    def extra_state_attributes(self) -> dict:
        groups = self.coordinator.data.get("groups", {})
        group = groups.get(self._group_id, {})
        return {
            "gruppo": self._group_id,
            "nome": self._group_name,
            "error_sign": group.get("errorsign", "OFF"),
            "codice_errore": group.get("errorcode", ""),
        }
