# 变更记录

## 1.2.0 — 网关 IP 漂移自动发现

网关地址由路由器 DHCP 下发，租约变化后会漂移。此前集成写死 `gateway_ip`，
一旦漂移就表现为「实体还在、状态冻结」，日志反复刷 `query all device status fail`，
必须手工改 `.storage` 才能恢复。

### 新增

- 新增 `discovery.py`：`async_discover_gateway()`
  - 对配置网段做 `/24` 的 TCP 80 扫描（并发 200，超时 0.8s，实测约 2s 扫完）
  - 端口指纹筛选：`80 + 5500 + 5600 + 9800 + 9900`
    （门口机/室内机是 `5500/5555/5600/8080/9800/9900`，**没有 80**，据此区分）
  - 读 `/proc/net/arp`，狄耐克 OUI `bc:f8:11` 的候选优先校验
  - 最终用已保存凭据请求 `/smart/iot.info` 确认身份，读得到才算数
- 启动钩子：`query_iot_info` 失败时自动触发扫描，命中后
  `async_update_entry` 写回 `gateway_ip`（无 update listener，不会触发重载）
- 运行时钩子：连续 6 次轮询失败触发扫描，冷却 600s，避免网关真离线时反复扫网段

### 改进

- `core/assistant.py` 所有 HTTP 请求增加 15s 超时
  - 原来无超时，网关不可达时 executor 线程会被长时间占用
- 新增 `Assistant.probe_host(ip)`：只读 `/smart/iot.info` 校验身份，不改 `gw_ip`

### 注意

- 安装/升级时**备份目录不要放在 `custom_components/` 下**
  - HA 会把 `dnake_home.bak-xxx` 当成组件名去 import，整个集成 setup 会失败
  - 备份请放到 `config/.bak_dnake/` 之类的位置

---

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
