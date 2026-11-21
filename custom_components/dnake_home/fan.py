"""新风系统（devType 16941）→ HA fan 实体。"""
import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.assistant import assistant
from .core.constant import DOMAIN, MANUFACTURER
from .core.utils import get_key_by_value

_LOGGER = logging.getLogger(__name__)

_fresh_air_dev_type = 16941

# 网关风速档位：0 低速 / 1 中速 / 2 高速 / 3 强劲
_fresh_air_speed_table = {
    0: "低速",
    1: "中速",
    2: "高速",
    3: "强劲",
}


def load_fans(device_list):
    fans = [
        DnakeFreshAir(device)
        for device in device_list
        if device.get("ty") == _fresh_air_dev_type
    ]
    _LOGGER.info(f"find fresh_air num: {len(fans)}")
    assistant.entries["fan"] = fans


def update_fans_state(states):
    fans = assistant.entries.get("fan", [])
    for fan in fans:
        state = next((state for state in states if fan.is_hint_state(state)), None)
        if state:
            fan.update_state(state)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    fan_list = assistant.entries.get("fan", [])
    if fan_list:
        async_add_entities(fan_list)


class DnakeFreshAir(FanEntity):

    def __init__(self, device):
        self._name = device.get("na")
        self._dev_no = device.get("nm")
        self._dev_ch = device.get("ch")
        self._dev_type = device.get("ty")
        self._is_on = device.get("powerOn", 0) == 1
        self._preset_mode = _fresh_air_speed_table.get(device.get("speed", 0), "低速")

    def is_hint_state(self, state):
        return (
            state.get("devType") == self._dev_type
            and state.get("devNo") == self._dev_no
            and state.get("devCh") == self._dev_ch
        )

    @property
    def unique_id(self):
        return f"dnake_fresh_air_{self._dev_no}_{self._dev_ch}"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, f"fresh_air_{self._dev_no}_{self._dev_ch}")},
            name=self._name,
            manufacturer=MANUFACTURER,
            model="新风控制",
            via_device=(DOMAIN, "gateway"),
        )

    @property
    def supported_features(self):
        return (
            FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.PRESET_MODE
        )

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def is_on(self):
        return self._is_on

    @property
    def preset_mode(self):
        return self._preset_mode

    @property
    def preset_modes(self):
        return list(_fresh_air_speed_table.values())

    async def _async_turn_to(self, is_open: bool):
        is_success = await self.hass.async_add_executor_job(
            assistant.set_fresh_air_power,
            self._dev_no,
            self._dev_ch,
            is_open,
        )
        if is_success:
            self._is_on = is_open
            self.async_write_ha_state()

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        await self._async_turn_to(True)

    async def async_turn_off(self, **kwargs):
        await self._async_turn_to(False)

    async def async_set_preset_mode(self, preset_mode):
        is_success = await self.hass.async_add_executor_job(
            assistant.set_fresh_air_flow,
            self._dev_no,
            self._dev_ch,
            get_key_by_value(_fresh_air_speed_table, preset_mode, 0),
        )
        if is_success:
            self._preset_mode = preset_mode
            self.async_write_ha_state()

    def update_state(self, state):
        self._is_on = state.get("powerOn", 0) == 1
        self._preset_mode = _fresh_air_speed_table.get(state.get("speed", 0), "低速")
        if self.hass is not None:
            self.async_write_ha_state()
