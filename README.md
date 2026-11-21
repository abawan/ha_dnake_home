# DNake Assistant 狄耐克集成（地暖 / 新风增强分支）

狄耐克集成是一个非官方提供支持的 Home Assistant 的集成组件，它可以让您在 Home Assistant 中使用狄耐克 IoT 智能设备。

本仓库是 [YangLang116/ha_dnake_home](https://github.com/YangLang116/ha_dnake_home) `v1.1.0` 的分支，
**在上游基础上新增地暖、新风支持，以及网关 IP 漂移自动发现、设备编号变化自愈等增强**，
不改变上游任何已有实体的 `unique_id` 与行为，可直接覆盖升级。

## 一、特性

- 灯具
    - 开灯
    - 关灯
- 窗帘
    - 打开窗帘
    - 关闭窗帘
    - 控制窗帘开合程度
    - 停止窗帘
- 空调面板
    - 开关空调
    - 查看室内温度
    - 设置温度：16 ~ 32 ℃
    - 设置模式：制冷、制热、送风、除湿
    - 设置风速：低速、中速、高速
    - 设置风向：横向摆风、纵向摆风
- **地暖（本分支新增，`devType 2048`）**
    - 开关地暖（`off` / `heat`）
    - 查看室内温度、设置目标温度：16 ~ 35 ℃，步进 1 ℃
    - 命令：`ctrlDev` + `airHeater` + `powerOn` / `powerOff` / `setTemp`
    - 典型设备：三合一面板（如 `BCAA-3IN1C-072`）上 `devCh=3` 的通道
- **新风（本分支新增，`devType 16941`）**
    - 开关新风系统
    - 设置风速：低速、中速、高速、强劲（对应网关 `speed 0~3`）
    - 附带 PM2.5 传感器（`device_class: pm25`）
    - 命令：`ctrlDev` + `airFresh` + `powerOn` / `powerOff` / `setFlow`

### 自愈能力（本分支新增）

- **网关 IP 漂移自动发现**：/24 TCP 80 扫描 + 端口指纹 `80/5500/5600/9800/9900` + OUI `bc:f8:11` 优先 + 凭据校验，实测 1.8 s 命中；运行时连续 6 次轮询失败同样触发
- **设备编号变化自愈**：网关重排 `devNo` 后，按设备名判定同一性并就地改写实体 `unique_id`，保留 `entity_id`、区域、历史与自动化引用
- **健康自检**：每 300 s 比对设备表指纹，只有「读到表且指纹变化」才重载；读不到表只做 IP 重发现，扫描失败指数退避，避免网关断电时反复重载

## 二、安装

> Home Assistant 版本要求：
>
> - Core $\geq$ 2024.4.4
> - Operating System $\geq$ 13.0

1、[HACS](https://hacs.xyz/) > 右上角三个点 > Custom repositories >
Repository: https://github.com/abawan/ha_dnake_home & Category or Type:
Integration > ADD

2、点击 HACS 的 New 或 Available for download 分类下的 Dnake Home ，进入集成详情页 > DOWNLOAD

3、重启 Home Assistant，然后在「设置 > 设备与服务 > 添加集成」中搜索 `Dnake Home` 完成配置。

> 覆盖安装提醒：如果此前手工把 `dnake_home` 放进了 `config/custom_components/`，
> HACS 会因目录已存在而拒绝安装，请先备份并移走该目录。
> **备份目录不要放在 `config/custom_components/` 下面**，否则 HA 会把 `dnake_home.bak-*`
> 当成组件名去 import，导致整个集成 setup 失败。

## 三、配置

- 网关：智能家居网关ip地址
- 登录账密：网关登录用户账密，默认: admin/123456
- 状态刷新间隔: 全量刷新设备状态的时间间隔

## 四、项目说明与支持

- 上游项目：本分支的基础代码来自 [YangLang116/ha_dnake_home](https://github.com/YangLang116/ha_dnake_home)。
  上游的部署协助、定制开发与有偿服务，请通过上游仓库或 `1004145468@qq.com` 联系原作者。
- 本分支定位：面向「地暖 + 新风 + 网关自愈」的增量增强，代码改动明细见 [CHANGELOG.md](CHANGELOG.md)，
  功能概览见 [info.md](info.md)。
- 问题反馈：本分支相关问题请提到 [本仓库 Issues](https://github.com/abawan/ha_dnake_home/issues)。

## 五、上游定制版本支持域

以下为上游作者提供定制开发的能力范围，供参考：

- 百叶窗
    - 控制升降程度
    - 调节百叶角度

- 热水器
    - 开关热水器
    - 设置水温
    - 查看剩余热水量

- 门锁
    - 开关门
    - 门锁警报

- 开窗器
    - 开关窗
    - 控制开合程度

- 空气盒子
    - 查看温度
    - 查看湿度
    - 查看PM2.5
