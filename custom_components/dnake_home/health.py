"""健康检查的决策逻辑（纯函数，便于单测）。

分离「设备表变化」和「网关不可达」两类信号，避免把「设备正常掉线/网关断电」
误判成「配置变了」，从而触发无意义的重载。
"""

from __future__ import annotations

ACTION_NONE = "none"
ACTION_DISCOVER = "discover"  # 只搜网段，不重载
ACTION_RELOAD = "reload"      # 设备表真的变了，重载同步

# 扫网段退避：没找到就逐步拉长间隔，避免网关长期离线时反复扫描
DISCOVERY_BASE = 600
DISCOVERY_MAX = 3600


def next_backoff(current: int, found: bool, base: int = DISCOVERY_BASE, cap: int = DISCOVERY_MAX) -> int:
    """一次发现动作结束后的冷却时长（秒）。找到就回到基准，没找到就翻倍（有上限）。"""
    if found:
        return base
    return min(max(int(current), base) * 2, cap)


def health_action(
    *, list_ok: bool, fingerprint_changed: bool, health_fail: int, fail_threshold: int
) -> str:
    """根据一次体检结果决定下一步动作。

    - 读到了设备表：只在指纹变化时重载（设备增删/改编号/改名）
    - 读不到设备表：只累计失败，达到阈值后**仅尝试重新发现网关**，
      绝不盲目重载 —— 网关断电时重载也必然失败，只会变成重试风暴
    """
    if list_ok:
        return ACTION_RELOAD if fingerprint_changed else ACTION_NONE
    if health_fail >= fail_threshold:
        return ACTION_DISCOVER
    return ACTION_NONE
