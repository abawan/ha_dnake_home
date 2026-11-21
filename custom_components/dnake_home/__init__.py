import logging
import time
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .core.assistant import assistant
from .cover import load_covers, update_covers_state
from .light import load_lights, update_lights_state
from .climate import load_climates, update_climates_state
from .fan import load_fans, update_fans_state
from .sensor import load_sensors, update_sensors_state
from .discovery import async_discover_gateway

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.COVER, Platform.CLIMATE, Platform.FAN, Platform.SENSOR]

# 连续多少次轮询失败后尝试重新发现网关
FAIL_THRESHOLD = 6
# 两次自动发现之间的最小间隔（秒），避免网关真离线时反复扫网段
DISCOVERY_COOLDOWN = 600


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    gateway_ip = entry.data["gateway_ip"]
    auth_username = entry.data["auth_username"]
    auth_password = entry.data["auth_password"]
    assistant.bind_auth_info(gateway_ip, auth_username, auth_password)

    iot_info = await hass.async_add_executor_job(assistant.query_iot_info)

    # 启动时连不上 → 网关可能因 DHCP 换了 IP，扫一遍网段
    if not iot_info:
        new_ip = await async_discover_gateway(hass, gateway_ip, assistant)
        if new_ip and new_ip != gateway_ip:
            _LOGGER.warning("网关地址已变更：%s -> %s，更新配置", gateway_ip, new_ip)
            assistant.bind_auth_info(new_ip, auth_username, auth_password)
            gateway_ip = new_ip
            # 集成未注册 update listener，此处只持久化数据，不会触发重载
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "gateway_ip": new_ip}
            )
            iot_info = await hass.async_add_executor_job(assistant.query_iot_info)

    if iot_info:
        iot_device_name = iot_info.get("iot_device_name")
        gw_iot_name = iot_info.get("gw_iot_name")
        assistant.bind_iot_info(iot_device_name, gw_iot_name)
        device_list = await hass.async_add_executor_job(assistant.query_device_list)
        if device_list:
            # 设备分类
            load_lights(device_list)
            load_covers(device_list)
            load_climates(device_list)
            load_fans(device_list)
            load_sensors(device_list)
            # 初始化各类设备
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

            state = {"fail": 0, "last_discovery": 0.0}

            async def _async_refresh_states(now=None):
                _LOGGER.info("update all device state")
                states = await hass.async_add_executor_job(assistant.read_all_dev_state)

                if not states:
                    # 连续失败 → 可能又是 IP 漂移，冷却后重新发现
                    state["fail"] += 1
                    if state["fail"] >= FAIL_THRESHOLD:
                        state["fail"] = 0
                        cooled = time.monotonic() - state["last_discovery"] >= DISCOVERY_COOLDOWN
                        if cooled:
                            state["last_discovery"] = time.monotonic()
                            new_ip = await async_discover_gateway(
                                hass, assistant.gw_ip, assistant
                            )
                            if new_ip and new_ip != assistant.gw_ip:
                                _LOGGER.warning(
                                    "运行中发现网关地址变更：%s -> %s，更新配置",
                                    assistant.gw_ip,
                                    new_ip,
                                )
                                assistant.bind_auth_info(new_ip, auth_username, auth_password)
                                hass.config_entries.async_update_entry(
                                    entry,
                                    data={**entry.data, "gateway_ip": new_ip},
                                )
                                states = await hass.async_add_executor_job(
                                    assistant.read_all_dev_state
                                )
                    if not states:
                        return
                else:
                    state["fail"] = 0

                update_lights_state(states)
                update_covers_state(states)
                update_climates_state(states)
                update_fans_state(states)
                update_sensors_state(states)

            # 初始化设备状态
            await _async_refresh_states()
            # 定时刷新设备状态
            time_delta = timedelta(seconds=entry.data["scan_interval"])
            async_track_time_interval(hass, _async_refresh_states, time_delta)
            return True
        else:
            _LOGGER.error("query_device_list fail")
            return False
    else:
        _LOGGER.error("query_iot_info fail")
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
