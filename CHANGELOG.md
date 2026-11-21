# 变更记录

## 1.1.1 — 新增地暖与新风支持

基于上游 `1.1.0`，仅做增量扩展，**不改变任何已有实体的 unique_id 与行为**。

### 新增：地暖（devType 2048）

- 新增 `climate` 实体 `DnakeHeater`
  - 模式：`off` / `heat`
  - 目标温度：16~35 ℃，步进 1
  - 当前温度取网关 `tempIndoor`，目标取 `tempDesire`
- 控制命令：`ctrlDev` + `cmd:airHeater` + `oper:powerOn|powerOff|setTemp`
- 典型设备：`BCAA-3IN1C-072` 三合一面板上 `devCh=3` 的地暖通道

### 新增：新风（devType 16941）

- 新增 `fan` 实体 `DnakeFreshAir`
  - 预设风速：低速 / 中速 / 高速 / 强劲（对应网关 `speed` 0~3）
  - 控制命令：`ctrlDev` + `cmd:airFresh` + `oper:powerOn|powerOff|setFlow`
- 新增 `sensor` 实体 `DnakePm25`
  - PM2.5，`device_class=pm25`，与 fan 挂在同一设备下

### 修复

- `light.py` / `cover.py` / `climate.py` 的 `update_state()` 增加 `self.hass is not None` 判空
  - 上游在 `async_forward_entry_setups()` 之后立即调用 `_async_refresh_states()`，
    此时实体尚未挂到 hass，`async_write_ha_state()` 会抛 `RuntimeError: Attribute hass is None`，
    导致整个集成 setup 失败
  - 触发条件：设备表变化（实体增删）后必然复现

### 兼容性

- 要求 Home Assistant ≥ 2024.x
- `__init__.py` 的 `PLATFORMS` 追加 `FAN`、`SENSOR`，并串联 `load_*/update_*`
- 已有实体（23 灯 / 6 空调 / 2 窗帘）的 `unique_id` 保持不变，升级不会产生重复或丢失
