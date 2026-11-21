import hashlib
import logging
import time
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .core.assistant import assistant
from .core.constant import DOMAIN
from .cover import load_covers, update_covers_state
from .light import load_lights, update_lights_state
from .climate import load_climates, update_climates_state
from .fan import load_fans, update_fans_state
from .sensor import load_sensors, update_sensors_state
from .discovery import async_discover_gateway
from .cleanup import async_cleanup_stale_devices
from .migrate import async_migrate_identity

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.COVER, Platform.CLIMATE, Platform.FAN, Platform.SENSOR]

# 连续多少次轮询失败后尝试重新发现网关
FAIL_THRESHOLD = 6
# 两次自动发现之间的最小间隔（秒），避免网关真离线时反复扫网段
DISCOVERY_COOLDOWN = 600
# 设备表体检间隔（秒）：网关改库/增删设备时据此触发重载
HEALTH_INTERVAL = 300
# 两次自动重载之间的最小间隔（秒），防止抖动引发重载风暴
RELOAD_COOLDOWN = 600


def _fingerprint(device_list) -> str:
    """设备表指纹：类型 + 编号 + 通道 + 名称，与顺序无关。"""
    rows = sorted(
        (str(d.get("ty")), str(d.get("nm")), str(d.get("ch")), str(d.get("na")))
        for d in device_list or []
    )
    raw = "|".join(":".join(r) for r in rows)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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
            # 设备编号被网关改过时，先把已有实体迁移到新地址（保住 entity_id/区域/历史）
            migrated = await async_migrate_identity(hass, device_list)
            if migrated:
                _LOGGER.warning("已完成 %d 个实体的身份迁移", migrated)

            # 设备分类
            load_lights(device_list)
            load_covers(device_list)
            load_climates(device_list)
            load_fans(device_list)
            load_sensors(device_list)
            # 初始化各类设备
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

            # 网关设备编号变化会留下空壳设备（无实体、无区域），顺手清理
            await async_cleanup_stale_devices(hass, device_list)

            state = {
                "fail": 0,
                "last_discovery": 0.0,
                "last_reload": 0.0,
                "baseline": _fingerprint(device_list),
            }

            def _schedule_reload(reason: str):
                """重载 = 重新走一遍：IP 校验 → 身份迁移 → 设备表同步 → 实体重建。"""
                if time.monotonic() - state["last_reload"] < RELOAD_COOLDOWN:
                    _LOGGER.debug("重载冷却中，跳过：%s", reason)
                    return
                state["last_reload"] = time.monotonic()
                _LOGGER.warning("触发集成重载：%s", reason)
                hass.config_entries.async_schedule_reload(entry.entry_id)

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
                                _schedule_reload(f"网关地址变为 {new_ip}")
                    if not states:
                        return
                else:
                    state["fail"] = 0

                update_lights_state(states)
                update_covers_state(states)
                update_climates_state(states)
                update_fans_state(states)
                update_sensors_state(states)

            async def _async_health_check(now=None):
                """设备表体检：改库、增删设备、换模块，都在这里被发现并触发重载。"""
                fresh = await hass.async_add_executor_job(assistant.query_device_list)
                if not fresh:
                    state["fail"] += 1
                    if state["fail"] >= FAIL_THRESHOLD:
                        state["fail"] = 0
                        _schedule_reload("设备表连续读取失败")
                    return

                state["fail"] = 0
                current = _fingerprint(fresh)
                if current != state["baseline"]:
                    _LOGGER.warning(
                        "设备表发生变化（%s -> %s，当前 %d 条），重载以同步设备与实体",
                        state["baseline"][:8],
                        current[:8],
                        len(fresh),
                    )
                    _schedule_reload("设备表变化")

            # 初始化设备状态
            await _async_refresh_states()
            # 定时刷新设备状态 + 周期性体检
            time_delta = timedelta(seconds=entry.data["scan_interval"])
            unsubs = [
                async_track_time_interval(hass, _async_refresh_states, time_delta),
                async_track_time_interval(
                    hass, _async_health_check, timedelta(seconds=HEALTH_INTERVAL)
                ),
            ]
            hass.data.setdefault(DOMAIN, {})[entry.entry_id] = unsubs
            return True
        else:
            _LOGGER.error("query_device_list fail")
            return False
    else:
        _LOGGER.error("query_iot_info fail")
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    for unsub in hass.data.get(DOMAIN, {}).pop(entry.entry_id, []):
        unsub()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
