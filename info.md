# Dnake Home（狄耐克智能家居）— 地暖 / 新风增强分支

基于 [YangLang116/ha_dnake_home](https://github.com/YangLang116/ha_dnake_home) `v1.1.0` 的增量分支，
**不改变上游任何已有实体的 `unique_id` 与行为**，可无缝覆盖升级。

## 相比上游多出来的能力

### 1. 地暖（`devType 2048`）→ `climate` 实体

- 模式 `off` / `heat`，目标温度 16~35 ℃，步进 1 ℃
- 当前温度 `tempIndoor`，目标温度 `tempDesire`
- 命令：`ctrlDev` + `airHeater` + `powerOn` / `powerOff` / `setTemp`
- 典型设备：`BCAA-3IN1C-072` 三合一墙面面板上的 `devCh=3` 通道

### 2. 新风（`devType 16941`）→ `fan` + `sensor`

- 预设风速：低速 / 中速 / 高速 / 强劲（网关 `speed 0~3`）
- 命令：`ctrlDev` + `airFresh` + `powerOn` / `powerOff` / `setFlow`
- 附带 PM2.5 `sensor`（`device_class: pm25`），与风机同设备

### 3. 网关 IP 漂移自动发现

路由器重新下发租约后网关换 IP，上游集成会「实体还在、状态冻结」。本分支启动时自动找回：

- 在配置网段做 `/24` TCP 80 扫描（并发 200、超时 0.8 s，实测约 2 s）
- 端口指纹过滤：网关 = `80 + 5500 + 5600 + 9800 + 9900`；门口机 / 室内机**没有 80**
- ARP 表里狄耐克 OUI `bc:f8:11` 优先探测，最后用已存凭据请求 `/smart/iot.info` 验明正身
- 运行时连续 6 次轮询失败同样触发，冷却 600 s，避免网关真离线时狂扫网段

### 4. 设备编号变化后的自愈（`cleanup.py` + `migrate.py`）

网关会给设备重排 `devNo`（实测 `24:x → 21:x`），上游按 `devNo_devCh` 拼标识，于是旧设备变成
无实体的空壳、新设备没有区域，用户在房间页里就「看不见」了。

- 按**设备名**判定同一设备，把实体 `unique_id` 就地改写 → `entity_id`、区域、历史、自动化引用全保留
- 空壳设备删除前先把区域迁给同名新设备
- 只处理本集成的设备，挂着实体的设备一律不碰，`gateway` 白名单

### 5. 健康自检（`health.py`）

每 300 s 拉一次设备表，和设备表指纹（`(ty,nm,ch,na)` 排序后 md5）比对：

| 信号 | 动作 |
|---|---|
| 读到表 且 指纹变了 | 重载（配置真的变了）|
| 读不到表 | 只累计失败，达阈值**仅重新发现 IP**，绝不盲目重载 |
| 探测当前 IP 可达 | 判为单个设备掉线，**不扫网段** |

`poll_fail` / `health_fail` 分开计数，重载有 600 s 冷却，定时器在 unload 时注销。
6 小时断电模拟：重载 0 次；单设备正常下线：重载 0 次、扫网段 0 次。

## 安装（HACS 自定义仓库）

1. HACS → 右上角 `⋮` → **自定义存储库**
2. 仓库地址填本仓库，类别选 **集成（Integration）**
3. 搜索 `Dnake Home` 安装，重启 Home Assistant
4. 设置 → 设备与服务 → 添加集成 → `Dnake Home`，填网关 IP、账号、密码

升级到本分支前建议备份 `config/.storage/core.config_entries`；
**备份目录不要放在 `config/custom_components/` 下面**，否则 HA 会把 `dnake_home.bak-xxx`
当成组件名去 import，整个集成 setup 失败。

## 兼容性

- Home Assistant ≥ 2024.4
- 已在 `BCAA-3IN1C-072` 三合一等面板 + 新风主机实测：36 实体 / 35 设备
