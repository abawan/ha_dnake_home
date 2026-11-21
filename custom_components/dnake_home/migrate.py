"""设备身份迁移：网关改了 devNo 时，把已有实体接到新地址上。

集成用 `devNo_devCh` 拼唯一标识（如 `light_24_7`），网关一旦重新分配编号
（实测主卧三盏灯 24:x -> 21:x），平台就会当成新设备、新建实体，旧实体变成
永远 `unavailable` 的孤儿。

这里用「房间里的设备名」作为同一性判据（网关 `na`，HA 设备名同源）：
    旧标识 light_24_7 + 名字「主卧灯带」  ==  新标识 light_21_7 + 名字「主卧灯带」
确认是同一台设备后，就地改写：

    - 实体 unique_id: light_24_7 -> light_21_7
    - 若新设备尚未存在：把旧设备的 identifiers 改成新标识（平台随后会复用它，区域不丢）
    - 若新设备已存在：把实体挂到新设备上，旧设备变成空壳由 cleanup 删除

这样 entity_id、区域、历史、自动化引用全部保留。

规划逻辑（`plan_migrations`）是纯函数，不碰 HA，便于单测。
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .core.constant import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 与各平台 DeviceInfo 中的 identifiers 保持一致
_ID_FORMATS = {
    256: "light_{}_{}",
    514: "cover_{}_{}",
    515: "cover_{}_{}",
    16640: "air_condition_{}_{}",
    2048: "heater_{}_{}",
    16941: "fresh_air_{}_{}",
}


def expected_uids(device_list) -> dict[str, dict]:
    """当前设备表应有的唯一标识 -> 设备信息。"""
    result: dict[str, dict] = {}
    for device in device_list or []:
        fmt = _ID_FORMATS.get(device.get("ty"))
        if not fmt:
            continue
        uid = fmt.format(device.get("nm"), device.get("ch"))
        result[uid] = device
    return result


def plan_migrations(device_list, entities, devices) -> list[dict]:
    """纯函数：算出需要迁移的实体清单。

    device_list: 网关设备表 [{"ty","nm","ch","na"}]
    entities:    实体注册表快照 [{"entity_id","unique_id","platform","device_id"}]
    devices:     设备注册表快照 [{"id","identifiers","name"}]
    """
    expected = expected_uids(device_list)
    if not expected:
        return []

    # 名字 -> 唯一标识（重名的一律不参与，避免误迁移）
    name_to_uid: dict[str, str] = {}
    dup_names: set[str] = set()
    for uid, device in expected.items():
        name = str(device.get("na") or "").strip()
        if not name:
            continue
        if name in name_to_uid:
            dup_names.add(name)
        name_to_uid[name] = uid
    for name in dup_names:
        name_to_uid.pop(name, None)

    device_by_id = {d["id"]: d for d in devices}
    # 已存在的新标识 -> 设备 id
    uid_to_device: dict[str, str] = {}
    for d in devices:
        for ident in d.get("identifiers") or []:
            if isinstance(ident, (list, tuple)) and len(ident) == 2 and ident[0] == DOMAIN:
                uid_to_device[str(ident[1])] = d["id"]

    used_uids = {e.get("unique_id") for e in entities if e.get("platform") == DOMAIN}

    plan: list[dict] = []
    for ent in entities:
        if ent.get("platform") != DOMAIN:
            continue
        uid = ent.get("unique_id")
        if not uid or uid in expected:
            continue  # 本来就对得上

        device = device_by_id.get(ent.get("device_id"))
        if not device:
            continue

        # 该设备的域内标识里，若有一个已在期望集合内，说明它没被改号
        own = [
            str(i[1]) for i in (device.get("identifiers") or [])
            if isinstance(i, (list, tuple)) and len(i) == 2 and i[0] == DOMAIN
        ]
        if any(i in expected for i in own):
            continue

        name = str(device.get("name") or "").strip()
        new_uid = name_to_uid.get(name)
        if not new_uid or new_uid == uid:
            continue
        if new_uid in used_uids:
            continue  # 已经有实体占用了新标识，放弃，交给清理逻辑

        plan.append(
            {
                "entity_id": ent["entity_id"],
                "old_uid": uid,
                "new_uid": new_uid,
                "old_device_id": device["id"],
                "target_device_id": uid_to_device.get(new_uid),
            }
        )
        used_uids.add(new_uid)

    return plan


async def async_migrate_identity(hass: HomeAssistant, device_list) -> int:
    """执行迁移，返回迁移条数。必须在创建平台实体之前调用。"""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    entities = [
        {
            "entity_id": e.entity_id,
            "unique_id": e.unique_id,
            "platform": e.platform,
            "device_id": e.device_id,
        }
        for e in ent_reg.entities.values()
    ]
    devices = [
        {"id": d.id, "identifiers": [list(i) for i in d.identifiers], "name": d.name}
        for d in dev_reg.devices.values()
    ]

    plan = plan_migrations(device_list, entities, devices)
    if not plan:
        return 0

    for item in plan:
        try:
            if item["target_device_id"]:
                # 新设备已存在：把实体挂过去，旧设备留空给 cleanup 收走
                ent_reg.async_update_entity(
                    item["entity_id"],
                    new_unique_id=item["new_uid"],
                    device_id=item["target_device_id"],
                )
            else:
                ent_reg.async_update_entity(
                    item["entity_id"], new_unique_id=item["new_uid"]
                )
                dev_reg.async_update_device(
                    item["old_device_id"],
                    new_identifiers={(DOMAIN, item["new_uid"])},
                )
            _LOGGER.warning(
                "设备编号变化，已迁移实体 %s：%s -> %s",
                item["entity_id"],
                item["old_uid"],
                item["new_uid"],
            )
        except Exception as e:  # noqa: BLE001 - 单条失败不影响其它
            _LOGGER.error("迁移失败 %s：%s", item["entity_id"], e)

    return len(plan)
