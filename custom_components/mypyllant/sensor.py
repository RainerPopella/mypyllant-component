from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ENERGY_WATT_HOUR, PERCENTAGE, PRESSURE_BAR, TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from myPyllant.models import (
    Circuit,
    Device,
    DeviceData,
    DeviceDataBucket,
    DomesticHotWater,
    System,
    Zone,
)

from . import DailyDataCoordinator, SystemCoordinator
from .const import DOMAIN
from .utils import get_name_prefix, get_unique_id_prefix

_LOGGER = logging.getLogger(__name__)

DATA_UNIT_MAP = {
    "CONSUMED_ELECTRICAL_ENERGY": ENERGY_WATT_HOUR,
    "EARNED_ENVIRONMENT_ENERGY": ENERGY_WATT_HOUR,
    "HEAT_GENERATED": ENERGY_WATT_HOUR,
    "CONSUMED_PRIMARY_ENERGY": ENERGY_WATT_HOUR,
    "EARNED_SOLAR_ENERGY": ENERGY_WATT_HOUR,
}


async def create_system_sensors(
    hass: HomeAssistant, config: ConfigEntry
) -> list[SensorEntity]:
    system_coordinator: SystemCoordinator = hass.data[DOMAIN][config.entry_id][
        "system_coordinator"
    ]
    if not system_coordinator.data:
        _LOGGER.warning("No system data, skipping sensors")
        return []

    sensors: list[SensorEntity] = []
    _LOGGER.debug("Creating system sensors for %s", system_coordinator.data)
    for index, system in enumerate(system_coordinator.data):
        if system.outdoor_temperature is not None:
            sensors.append(SystemOutdoorTemperatureSensor(index, system_coordinator))
        if system.water_pressure is not None:
            sensors.append(SystemWaterPressureSensor(index, system_coordinator))
        sensors.append(HomeEntity(index, system_coordinator))

        for device_index, device in enumerate(system.devices):
            _LOGGER.debug("Creating SystemDevice sensors for %s", device)

            if "water_pressure" in device.operational_data:
                sensors.append(
                    SystemDeviceWaterPressureSensor(
                        index, device_index, system_coordinator
                    )
                )

        for zone_index, zone in enumerate(system.zones):
            _LOGGER.debug("Creating Zone sensors for %s", zone)
            sensors.append(
                ZoneDesiredRoomTemperatureSetpointSensor(
                    index, zone_index, system_coordinator
                )
            )
            if zone.current_room_temperature is not None:
                sensors.append(
                    ZoneCurrentRoomTemperatureSensor(
                        index, zone_index, system_coordinator
                    )
                )
            if zone.current_room_humidity is not None:
                sensors.append(
                    ZoneHumiditySensor(index, zone_index, system_coordinator)
                )
            sensors.append(
                ZoneHeatingOperatingModeSensor(index, zone_index, system_coordinator)
            )
            sensors.append(
                ZoneHeatingStateSensor(index, zone_index, system_coordinator)
            )
            sensors.append(
                ZoneCurrentSpecialFunctionSensor(index, zone_index, system_coordinator)
            )

        for circuit_index, circuit in enumerate(system.circuits):
            _LOGGER.debug("Creating Circuit sensors for %s", circuit)
            sensors.append(CircuitStateSensor(index, circuit_index, system_coordinator))
            if circuit.current_circuit_flow_temperature is not None:
                sensors.append(
                    CircuitFlowTemperatureSensor(
                        index, circuit_index, system_coordinator
                    )
                )
            if circuit.heating_curve is not None:
                sensors.append(
                    CircuitHeatingCurveSensor(index, circuit_index, system_coordinator)
                )
            if circuit.min_flow_temperature_setpoint is not None:
                sensors.append(
                    CircuitMinFlowTemperatureSetpointSensor(
                        index, circuit_index, system_coordinator
                    )
                )

        for dhw_index, dhw in enumerate(system.domestic_hot_water):
            _LOGGER.debug("Creating Domestic Hot Water sensors for %s", dhw)
            if dhw.current_dhw_temperature:
                sensors.append(
                    DomesticHotWaterTankTemperatureSensor(
                        index, dhw_index, system_coordinator
                    )
                )
            sensors.append(
                DomesticHotWaterSetPointSensor(index, dhw_index, system_coordinator)
            )
            sensors.append(
                DomesticHotWaterOperationModeSensor(
                    index, dhw_index, system_coordinator
                )
            )
            sensors.append(
                DomesticHotWaterCurrentSpecialFunctionSensor(
                    index, dhw_index, system_coordinator
                )
            )
    return sensors


async def create_daily_data_sensors(
    hass: HomeAssistant, config: ConfigEntry
) -> list[SensorEntity]:
    daily_data_coordinator: DailyDataCoordinator = hass.data[DOMAIN][config.entry_id][
        "daily_data_coordinator"
    ]

    _LOGGER.debug("Daily data: %s", daily_data_coordinator.data)

    if not daily_data_coordinator.data:
        _LOGGER.warning("No daily data, skipping sensors")
        return []

    sensors: list[SensorEntity] = []
    for system_id, system_devices in daily_data_coordinator.data.items():
        _LOGGER.debug("Creating efficiency sensor for System %s", system_id)
        sensors.append(EfficiencySensor(system_id, None, daily_data_coordinator))
        for de_index, devices_data in enumerate(system_devices["devices_data"]):
            if len(devices_data) == 0:
                continue
            _LOGGER.debug(
                "Creating efficiency sensor for System %s and Device %i",
                system_id,
                de_index,
            )
            sensors.append(
                EfficiencySensor(system_id, de_index, daily_data_coordinator)
            )
            for da_index, _ in enumerate(
                daily_data_coordinator.data[system_id]["devices_data"][de_index]
            ):
                sensors.append(
                    DataSensor(system_id, de_index, da_index, daily_data_coordinator)
                )

    return sensors


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(await create_system_sensors(hass, config))
    async_add_entities(await create_daily_data_sensors(hass, config))


class SystemSensor(CoordinatorEntity, SensorEntity):
    coordinator: SystemCoordinator

    def __init__(self, index: int, coordinator: SystemCoordinator) -> None:
        super().__init__(coordinator)
        self.index = index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.index]

    @property
    def device_info(self) -> DeviceInfo | None:
        return {"identifiers": {(DOMAIN, f"home_{self.system.id}")}}


class SystemOutdoorTemperatureSensor(SystemSensor):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.system.outdoor_temperature is not None:
            return round(self.system.outdoor_temperature, 1)
        else:
            return None

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}outdoor_temperature"

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Outdoor Temperature"


class SystemWaterPressureSensor(SystemSensor):
    _attr_native_unit_of_measurement = PRESSURE_BAR
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.system.water_pressure is not None:
            return round(self.system.water_pressure, 1)
        else:
            return None

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}water_pressure_{self.index}"

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}System Water Pressure"


class HomeEntity(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        system_index: int,
        coordinator: SystemCoordinator,
    ):
        super().__init__(coordinator)
        self.system_index = system_index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.system.home.extra_fields | self.system.extra_fields

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, f"home_{self.system.id}")},
            name=f"{self.system.home.name}",
            manufacturer=self.system.brand_name,
            model=self.system.home.nomenclature,
            sw_version=self.system.home.firmware_version,
        )

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}home"

    @property
    def native_value(self):
        return self.system.home.firmware_version

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Firmware Version"


class ZoneEntity(CoordinatorEntity, SensorEntity):
    coordinator: SystemCoordinator

    def __init__(
        self, system_index: int, zone_index: int, coordinator: SystemCoordinator
    ) -> None:
        super().__init__(coordinator)
        self.system_index = system_index
        self.zone_index = zone_index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def zone(self) -> Zone:
        return self.system.zones[self.zone_index]

    @property
    def circuit_name_suffix(self) -> str:
        if self.zone.associated_circuit_index is None:
            return ""
        else:
            return f" of Circuit {self.zone.associated_circuit_index}"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, f"zone_{self.system.id}_{self.zone.index}")},
            name=f"{get_name_prefix(self.system.home.name)}Zone {self.zone.name}{self.circuit_name_suffix}",
            manufacturer=self.system.brand_name,
        )

    @property
    def available(self) -> bool | None:
        return self.zone.is_active


class ZoneDesiredRoomTemperatureSetpointSensor(ZoneEntity):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Desired Temperature in {self.zone.name}"

    @property
    def native_value(self):
        if self.zone.desired_room_temperature_setpoint_heating:
            return self.zone.desired_room_temperature_setpoint_heating
        elif self.zone.desired_room_temperature_setpoint_cooling:
            return self.zone.desired_room_temperature_setpoint_cooling
        else:
            return self.zone.desired_room_temperature_setpoint

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_desired_temperature_{self.zone_index}"


class ZoneCurrentRoomTemperatureSensor(ZoneEntity):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Current Temperature in {self.zone.name}"

    @property
    def native_value(self):
        return (
            None
            if self.zone.current_room_temperature is None
            else round(self.zone.current_room_temperature, 1)
        )

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_current_temperature_{self.zone_index}"


class ZoneHumiditySensor(ZoneEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Humidity in {self.zone.name}"

    @property
    def native_value(self):
        return self.zone.current_room_humidity

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_humidity_{self.zone_index}"


class ZoneHeatingOperatingModeSensor(ZoneEntity):
    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Heating Operating Mode in {self.zone.name}"

    @property
    def native_value(self):
        return self.zone.heating.operation_mode_heating.display_value

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_heating_operating_mode_{self.zone_index}"

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC


class ZoneHeatingStateSensor(ZoneEntity):
    @property
    def name(self):
        return (
            f"{get_name_prefix(self.system.home.name)}Heating State in {self.zone.name}"
        )

    @property
    def native_value(self):
        return self.zone.heating_state.display_value

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_heating_state_{self.zone_index}"

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC


class ZoneCurrentSpecialFunctionSensor(ZoneEntity):
    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Current Special Function in {self.zone.name}"

    @property
    def native_value(self):
        return self.zone.current_special_function.display_value

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}zone_current_special_function_{self.zone_index}"

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC


class CircuitSensor(CoordinatorEntity, SensorEntity):
    coordinator: SystemCoordinator

    def __init__(
        self, system_index: int, circuit_index: int, coordinator: SystemCoordinator
    ) -> None:
        super().__init__(coordinator)
        self.system_index = system_index
        self.circuit_index = circuit_index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def circuit(self) -> Circuit:
        return self.system.circuits[self.circuit_index]

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"circuit_{self.system.id}_{self.circuit.index}")}
        }


class CircuitFlowTemperatureSensor(CircuitSensor):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Current Flow Temperature in Circuit {self.circuit.index}"

    @property
    def native_value(self):
        return self.circuit.current_circuit_flow_temperature

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}circuit_flow_temperature_{self.circuit_index}"


class CircuitStateSensor(CircuitSensor):
    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}State in Circuit {self.circuit.index}"

    @property
    def native_value(self):
        return self.circuit.circuit_state

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.circuit.extra_fields

    @property
    def unique_id(self) -> str:
        return (
            f"{get_unique_id_prefix(self.system.id)}circuit_state_{self.circuit_index}"
        )


class CircuitMinFlowTemperatureSetpointSensor(CircuitSensor):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Min Flow Temperature Setpoint in Circuit {self.circuit.index}"

    @property
    def native_value(self):
        return self.circuit.min_flow_temperature_setpoint

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}circuit_min_flow_temperature_setpoint_{self.circuit_index}"


class CircuitHeatingCurveSensor(CircuitSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Heating Curve in Circuit {self.circuit.index}"

    @property
    def native_value(self):
        if self.circuit.heating_curve is not None:
            return round(self.circuit.heating_curve, 2)
        else:
            return None

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}circuit_heating_curve_{self.circuit_index}"


class DomesticHotWaterSensor(CoordinatorEntity, SensorEntity):
    coordinator: SystemCoordinator

    def __init__(
        self, system_index: int, dhw_index: int, coordinator: SystemCoordinator
    ) -> None:
        super().__init__(coordinator)
        self.system_index = system_index
        self.dhw_index = dhw_index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def domestic_hot_water(self) -> DomesticHotWater:
        return self.system.domestic_hot_water[self.dhw_index]

    @property
    def device_info(self):
        return {
            "identifiers": {
                (
                    DOMAIN,
                    f"domestic_hot_water_{self.system.id}_{self.domestic_hot_water.index}",
                )
            }
        }


class DomesticHotWaterTankTemperatureSensor(DomesticHotWaterSensor):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Tank Temperature Domestic Hot Water {self.domestic_hot_water.index}"

    @property
    def native_value(self):
        return self.domestic_hot_water.current_dhw_temperature

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}dhw_tank_temperature_{self.dhw_index}"


class DomesticHotWaterSetPointSensor(DomesticHotWaterSensor):
    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Setpoint Domestic Hot Water {self.domestic_hot_water.index}"

    @property
    def native_value(self) -> float | None:
        return self.domestic_hot_water.tapping_setpoint

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}dhw_set_point_{self.dhw_index}"


class DomesticHotWaterOperationModeSensor(DomesticHotWaterSensor):
    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Operation Mode Domestic Hot Water {self.domestic_hot_water.index}"

    @property
    def native_value(self):
        return self.domestic_hot_water.operation_mode_dhw.display_value

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return (
            f"{get_unique_id_prefix(self.system.id)}dhw_operation_mode_{self.dhw_index}"
        )


class DomesticHotWaterCurrentSpecialFunctionSensor(DomesticHotWaterSensor):
    @property
    def name(self):
        return f"{get_name_prefix(self.system.home.name)}Current Special Function Domestic Hot Water {self.domestic_hot_water.index}"

    @property
    def native_value(self):
        return self.domestic_hot_water.current_special_function.display_value

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}dhw_current_special_function_{self.dhw_index}"


class DataSensor(CoordinatorEntity, SensorEntity):
    coordinator: DailyDataCoordinator
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        system_id: str,
        de_index: int,
        da_index: int,
        coordinator: DailyDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.system_id = system_id
        self.da_index = da_index
        self.de_index = de_index
        if (
            self.device_data is not None
            and self.device_data.energy_type in DATA_UNIT_MAP
        ):
            self._attr_native_unit_of_measurement = DATA_UNIT_MAP[
                self.device_data.energy_type
            ]
        self._attr_device_class = SensorDeviceClass.ENERGY
        _LOGGER.debug(
            "Finishing init of %s = %s and unique id %s",
            self.name,
            self.native_value,
            self.unique_id,
        )

    @property
    def name(self):
        if self.device is None or self.device_data is None:
            return None
        name = self.device.name_display
        om = self.device_data.operation_mode.replace("_", " ").title()
        et = (
            self.device_data.energy_type.replace("_", " ").title() + " "
            if self.device_data.energy_type is not None
            else ""
        )
        return f"{get_name_prefix(self.home_name)}{self.de_index} {name} {et}{om}"

    @property
    def device_data(self) -> DeviceData | None:
        if len(self.coordinator.data[self.system_id]["devices_data"]) <= self.de_index:
            return None
        if (
            len(self.coordinator.data[self.system_id]["devices_data"][self.de_index])
            <= self.da_index
        ):
            return None
        return self.coordinator.data[self.system_id]["devices_data"][self.de_index][
            self.da_index
        ]

    @property
    def home_name(self) -> str:
        return self.coordinator.data[self.system_id]["home_name"]

    @property
    def device(self) -> Device | None:
        if self.device_data is None:
            return None
        return self.device_data.device

    @property
    def data_bucket(self) -> DeviceDataBucket | None:
        if self.device_data is None:
            return None
        data = [d for d in self.device_data.data if d.value is not None]
        if len(data) > 0:
            return data[-1]
        else:
            return None

    @property
    def unique_id(self) -> str | None:
        if self.device is None:
            return None
        return f"{get_unique_id_prefix(self.system_id)}{self.device.device_uuid}_{self.da_index}"

    @property
    def device_info(self):
        if self.device is None:
            return None
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"device_{self.system_id}_{self.device.device_uuid}")
            },
            name=f"{get_name_prefix(self.home_name)}{self.de_index} {self.device.name_display}",
            manufacturer=self.device.brand_name,
            model=self.device.product_name_display,
        )

    @property
    def native_value(self):
        return self.data_bucket.value if self.data_bucket else None

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        _LOGGER.debug(
            "Updated DataSensor %s = %s last reset on %s, from data %s",
            self.unique_id,
            self.native_value,
            self.last_reset,
            self.device_data.data if self.device_data is not None else None,
        )


class EfficiencySensor(CoordinatorEntity, SensorEntity):
    coordinator: DailyDataCoordinator
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, system_id: str, de_index: int | None, coordinator: DailyDataCoordinator
    ) -> None:
        super().__init__(coordinator)
        self.system_id = system_id
        self.de_index = de_index

    @property
    def device_data_list(self) -> list[DeviceData]:
        if self.de_index is None:
            return [
                item
                for row in self.coordinator.data[self.system_id]["devices_data"]
                for item in row
            ]
        else:
            return self.coordinator.data[self.system_id]["devices_data"][self.de_index]

    @property
    def home_name(self) -> str:
        return self.coordinator.data[self.system_id]["home_name"]

    @property
    def energy_consumed(self) -> float:
        """
        Returns total consumed electrical energy for the current day
        """
        return sum(
            [
                v.data[-1].value
                for v in self.device_data_list
                if len(v.data)
                and v.data[-1].value
                and v.energy_type == "CONSUMED_ELECTRICAL_ENERGY"
            ]
        )

    @property
    def heat_energy_generated(self) -> float:
        """
        Returns total generated heating energy for the current day
        """
        return sum(
            [
                v.data[-1].value
                for v in self.device_data_list
                if len(v.data)
                and v.data[-1].value
                and v.energy_type == "HEAT_GENERATED"
            ]
        )

    @property
    def unique_id(self) -> str:
        if (
            len(self.device_data_list) > 0
            and self.de_index is not None
            and self.device_data_list[0].device is not None
        ):
            return f"{get_unique_id_prefix(self.system_id)}{self.device_data_list[0].device.device_uuid}_heating_energy_efficiency"
        else:
            return f"{get_unique_id_prefix(self.system_id)}heating_energy_efficiency"

    @property
    def device_info(self):
        if len(self.device_data_list) == 0:
            return None
        if self.de_index is not None and self.device_data_list[0].device is not None:
            return {
                "identifiers": {
                    (
                        DOMAIN,
                        f"device_{self.system_id}_{self.device_data_list[0].device.device_uuid}",
                    )
                }
            }
        elif self.de_index is None:
            return {"identifiers": {(DOMAIN, f"home_{self.system_id}")}}
        else:
            return None

    @property
    def native_value(self) -> float | None:
        if self.energy_consumed is not None and self.energy_consumed > 0:
            return round(self.heat_energy_generated / self.energy_consumed, 1)
        else:
            return None

    @property
    def name(self):
        if (
            len(self.device_data_list) > 0
            and self.de_index is not None
            and self.device_data_list[0].device is not None
        ):
            return f"{get_name_prefix(self.home_name)}{self.de_index} {self.device_data_list[0].device.name_display} Heating Energy Efficiency"
        else:
            return f"{get_name_prefix(self.home_name)}Heating Energy Efficiency"


class SystemDeviceSensor(CoordinatorEntity, SensorEntity):
    coordinator: SystemCoordinator

    def __init__(
        self, system_index: int, device_index: int, coordinator: SystemCoordinator
    ) -> None:
        super().__init__(coordinator)
        self.system_index = system_index
        self.device_index = device_index

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def device(self) -> Device:
        return self.system.devices[self.device_index]

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, f"system_{self.system.id}")}}


class SystemDeviceWaterPressureSensor(SystemDeviceSensor):
    _attr_native_unit_of_measurement = PRESSURE_BAR
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        return (
            f"{get_name_prefix(self.system.home.name)}Water Pressure {self.device.name}"
        )

    @property
    def native_value(self):
        return self.device.operational_data.get("water_pressure", {}).get("value")

    @property
    def unique_id(self) -> str:
        return f"{get_unique_id_prefix(self.system.id)}water_pressure_{self.device.device_uuid}"

    @property
    def entity_category(self) -> EntityCategory | None:
        return EntityCategory.DIAGNOSTIC
