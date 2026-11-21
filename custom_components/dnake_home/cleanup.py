"""网关设备编号变化后的幽灵设备清理。

背景：集成用 `devNo_devCh` 拼设备标识（如 `light_21_7`），唯一 ID 也基于它。
网关一旦给某个设备重新分配编号（实测主卧灯带 24:7 -> 21:7），集成会把它当成
新设备，于是：
    - 旧设备留在注册表里，没有任何实体 → 房间页看不到内容
    - 新设备拿到了实体，但没有用户之前设置的区域 → 房间页里也看不到

用户看到的现象就是「明明 App 里有，HA 里不见了」。

这里做两件事：
    1. 把旧设备上的区域（area）迁移给同名的现存设备
    2. 删除既无实体、又不在当前设备列表里的空壳设备

只处理本集成（dnake_home）的设备，且**不碰任何挂着实体的设备**，避免误删。
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .core.constant import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 设备类型 -> 标识格式，与各平台 DeviceInfo 中的 identifiers 保持一致
_ID_FORMATS = {
    256: "light_{}_{}",          # 灯
    514: "cover_{}_{}",          # 窗帘
    515: "cover_{}_{}",          # 窗帘
    16640: "air_condition_{}_{}",  # 空调
    2048: "heater_{}_{}",        # 地暖
    16941: "fresh_air_{}_{}",    # 新风
}

# 这些标识即使不在设备列表里也不能删（被 via_device 引用）
_RESERVED = {"gateway"}


def _expected_identifiers(device_list) -> set[str]:
    ids: set[str] = set()
    for device in device_list or []:
        fmt = _ID_FORMATS.get(device.get("ty"))
        if not fmt:
            continue
        ids.add(fmt.format(device.get("nm"), device.get("ch")))
    return ids


async def async_cleanup_stale_devices(hass: HomeAssistant, device_list) -> None:
    """迁移区域并清理空壳设备。幂等，每次启动都可安全调用。"""
    expected = _expected_identifiers(device_list)
    if not expected:
        return

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    live: dict[str, object] = {}
    stale = []
    for device in list(dev_reg.devices.values()):
        ids = [value for domain, value in device.identifiers if domain == DOMAIN]
        if not ids:
            continue
        if any(value in _RESERVED for value in ids):
            continue
        if any(value in expected for value in ids):
            live[str(device.name)] = device
        else:
            stale.append(device)

    if not stale:
        return

    for device in stale:
        entities = er.async_entries_for_device(ent_reg, device.id)
        if entities:
            # 还挂着实体，说明有别的用途，不动
            _LOGGER.debug("跳过有实体的旧设备 %s（%d 个实体）", device.name, len(entities))
            continue

        twin = live.get(str(device.name))
        if twin is not None and not twin.area_id and device.area_id:
            # 把用户之前设好的区域迁移过去（新旧同名才是同一个物理设备）
            dev_reg.async_update_device(twin.id, area_id=device.area_id)
            _LOGGER.warning(
                "设备编号变化，已把区域从旧条目迁到新条目：%s -> %s", device.name, twin.area_id
            )

        _LOGGER.warning(
            "清理空壳设备：%s %s", device.name, sorted(device.identifiers)
        )
        dev_reg.async_remove_device(device.id)
