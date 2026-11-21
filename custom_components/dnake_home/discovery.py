"""狄耐克网关 IP 漂移自动发现。

网关的地址由路由器 DHCP 下发，租约变化后会漂移（实测从 .195 漂到 .236），
集成写死了旧 IP 就会一直连不上，表现为：
    实体还在，但状态冻结；日志反复刷 "query all device status fail"。

本模块在两种时机重新定位网关：
    1. 集成启动时连不上 → 扫一遍
    2. 运行中连续多次轮询失败 → 扫一遍（有冷却时间，避免频繁扫描）

定位策略（逐层收窄，尽量不误判）：
    1. 对配置网段的 /24 做 TCP 80 探测（并发、短超时），得到候选
    2. 端口指纹筛选：80 + 5500 + 5600 + 9800 + 9900
       —— 这是网关独有的组合；门口机/室内机没有 80，只有 5500/5555/5600/8080/9800/9900
    3. 读 /proc/net/arp，优先取狄耐克 OUI（bc:f8:11）的候选
    4. 用已保存的账号密码请求 /smart/iot.info 做最终确认（能读到数据才算数）
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging

_LOGGER = logging.getLogger(__name__)

# 网关固定开放的端口组合，用于和门口机/室内机区分
_GATEWAY_PORTS = (5500, 5600, 9800, 9900)

# 狄耐克 OUI
_DNAKE_OUIS = ("bc:f8:11",)

# 扫描参数
_CONNECT_TIMEOUT = 0.8
_MAX_CONCURRENCY = 200
_PORT_PROBE_TIMEOUT = 1.0

_scan_lock = asyncio.Lock()


async def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
    except (asyncio.TimeoutError, OSError):
        return False
    except Exception:  # noqa: BLE001 - 任何异常都视作不可达
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return True


def _subnet_hosts(ip: str, prefix: int = 24) -> list[str]:
    try:
        net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
    except ValueError:
        return []
    return [str(h) for h in net.hosts()]


def _read_arp_table() -> dict[str, str]:
    """读本机邻居表，ip -> mac。容器内只能看到自己通信过的条目。"""
    table: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                    table[parts[0]] = parts[3].lower()
    except OSError:
        pass
    return table


async def _has_gateway_fingerprint(ip: str) -> bool:
    """端口指纹：必须是网关那组端口，而不是门口机。"""
    results = await asyncio.gather(
        *(_tcp_open(ip, p, _PORT_PROBE_TIMEOUT) for p in _GATEWAY_PORTS)
    )
    return all(results)


async def _find_candidates(hosts: list[str]) -> list[str]:
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def probe(ip: str) -> str | None:
        async with sem:
            if await _tcp_open(ip, 80, _CONNECT_TIMEOUT):
                return ip
            return None

    results = await asyncio.gather(*(probe(ip) for ip in hosts))
    opened = [ip for ip in results if ip]

    if not opened:
        return []

    checks = await asyncio.gather(*(_has_gateway_fingerprint(ip) for ip in opened))
    return [ip for ip, ok in zip(opened, checks) if ok]


async def async_discover_gateway(hass, current_ip: str, assistant) -> str | None:
    """在当前网段内找网关，找到就返回新 IP，否则返回 None。

    assistant 需已 bind_auth_info（用它的凭据做最终校验）。
    """
    hosts = _subnet_hosts(current_ip)
    if not hosts:
        _LOGGER.error("网关发现失败：无法推导网段 ip=%s", current_ip)
        return None

    if _scan_lock.locked():
        _LOGGER.debug("已有扫描在进行，跳过")
        return None

    async with _scan_lock:
        _LOGGER.warning("开始扫描网段 %s/24 查找狄耐克网关…", current_ip.rsplit(".", 1)[0])
        candidates = await _find_candidates(hosts)
        if not candidates:
            _LOGGER.error("扫描完成：未发现符合端口指纹的设备")
            return None

        # 按 MAC OUI 排序，狄耐克设备优先校验
        arp = await hass.async_add_executor_job(_read_arp_table)
        def _rank(ip: str) -> tuple[int, int]:
            mac = arp.get(ip, "")
            is_dnake = any(mac.startswith(oui) for oui in _DNAKE_OUIS)
            return (0 if is_dnake else 1, 0 if ip == current_ip else 1)

        candidates.sort(key=_rank)
        _LOGGER.info(
            "端口指纹命中 %s 台：%s",
            len(candidates),
            ", ".join(f"{ip}({arp.get(ip, '?')})" for ip in candidates),
        )

        for ip in candidates:
            if await hass.async_add_executor_job(assistant.probe_host, ip):
                return ip

        _LOGGER.error("候选设备均无法用已保存凭据登录，放弃自动切换")
        return None
