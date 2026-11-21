"""新风 PM2.5 传感器（devType 16941）。"""
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.assistant import assistant
from .core.constant import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

_fresh_air_dev_type = 16941


def load_sensors(device_list):
    sensors = [
        DnakePm25(device)
        for device in device_list
        if device.get("ty") == _fresh_air_dev_type
    ]
    _LOGGER.info(f"find pm25 sensor num: {len(sensors)}")
    assistant.entries["sensor"] = sensors


def update_sensors_state(states):
    sensors = assistant.entries.get("sensor", [])
    for sensor in sensors:
        state = next((state for state in states if sensor.is_hint_state(state)), None)
        if state:
            sensor.update_state(state)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    sensor_list = assistant.entries.get("sensor", [])
    if sensor_list:
        async_add_entities(sensor_list)


class DnakePm25(SensorEntity):

    def __init__(self, device):
        self._name = device.get("na")
        self._dev_no = device.get("nm")
        self._dev_ch = device.get("ch")
        self._dev_type = device.get("ty")
        self._value = device.get("pm25", 0)

    def is_hint_state(self, state):
        return (
            state.get("devType") == self._dev_type
            and state.get("devNo") == self._dev_no
            and state.get("devCh") == self._dev_ch
        )

    @property
    def unique_id(self):
        return f"dnake_fresh_air_pm25_{self._dev_no}_{self._dev_ch}"

    @property
    def device_info(self):
        # 与 fan 实体挂在同一个设备上
        return DeviceInfo(
            identifiers={(DOMAIN, f"fresh_air_{self._dev_no}_{self._dev_ch}")},
            name=self._name,
            manufacturer=MANUFACTURER,
            model="新风控制",
            via_device=(DOMAIN, "gateway"),
        )

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return f"{self._name} PM2.5"

    @property
    def native_value(self):
        return self._value

    @property
    def native_unit_of_measurement(self):
        return CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

    @property
    def device_class(self):
        return SensorDeviceClass.PM25

    @property
    def state_class(self):
        return SensorStateClass.MEASUREMENT

    def update_state(self, state):
        self._value = state.get("pm25", 0)
        if self.hass is not None:
            self.async_write_ha_state()
