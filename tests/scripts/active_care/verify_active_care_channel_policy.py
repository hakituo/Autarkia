#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证主动关怀投递渠道策略，并打印「渠道决策矩阵」供人工判断。

矩阵是这份脚本的主要产出：把四种模式 × 各场景的投递结果列成表，
用户据此决定 `life_simulation.active_care_channel_mode` 该取哪个值。

用法：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_active_care_channel_policy.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_active_care_channel_policy.py --report 2026-10-13
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.active_care.core.channel_policy import (  # noqa: E402
    MODE_MIRROR_APP,
    MODE_PREFER_APP,
    MODE_PREFER_QQ,
    MODE_SMART,
    VALID_MODES,
    decide_channel,
)

FAILURES: list[str] = []

# 判断用的场景表：(说明, 消息类型, App 是否在线, 用户最近活跃端)
SCENARIOS = [
    ("作息/健康类 · 两端都在线", "user_health_reminder", True, "app"),
    ("作息/健康类 · 用户在 QQ", "goodnight_proactive", True, "qq"),
    ("普通话题 · 用户在 App", "curious_question", True, "app"),
    ("普通话题 · 用户在 QQ", "curious_question", True, "qq"),
    ("普通话题 · 活跃端未知", "curious_question", True, ""),
    ("普通话题 · App 离线", "curious_question", False, "app"),
]


def _check(condition: bool, label: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}{('  ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def verify_wiring() -> None:
    """确认策略模块已接进真实投递链路，且用的是正确的活跃端信号。"""
    print("[1] 投递链路接线")
    source = (
        PROJECT_ROOT / "core/services/aveline/proactive_messaging.py"
    ).read_text(encoding="utf-8")
    _check("decide_channel" in source, "proactive_messaging 调用渠道策略")
    _check("channel.deliver_qq" in source, "QQ 主投受策略控制")
    _check("channel.deliver_app" in source, "App 补投受策略控制")
    _check("回退 QQ 主投" in source, "App 优先失败时回退 QQ（不丢消息）")
    # 2026-10-16 回归点：判「用户在哪个端」必须用 channel_probe，
    # 不能用 probe_client_type()（它只要 QQ 连着就返回 qq）
    _check(
        "detect_user_active_channel" in source,
        "用 channel_probe 判用户活跃端（而非 probe_client_type）",
    )
    _check(
        "user_active_channel=user_active_channel" in source,
        "活跃端信号已传给渠道策略",
    )

    settings = (PROJECT_ROOT / "config/settings_life.py").read_text(encoding="utf-8")
    _check("active_care_channel_mode" in settings, "active_care_channel_mode 已声明")
    _check(
        "active_care_channel_probe_max_age_seconds" in settings,
        "活跃端信号有效期已声明",
    )


def verify_safety() -> None:
    """任何模式任何场景都不能两端都不发。"""
    print("[2] 安全性：不存在「两端都不发」的组合")
    bad = []
    for mode in VALID_MODES:
        for prompt_type in ("user_health_reminder", "curious_question", ""):
            for app_online in (True, False):
                for active in ("", "app", "qq"):
                    for origin in ("", "qq", "websocket"):
                        decision = decide_channel(
                            sys_prompt_type=prompt_type,
                            app_online=app_online,
                            user_active_channel=active,
                            requested_client_type=origin,
                            mode=mode,
                        )
                        if not (decision.deliver_qq or decision.deliver_app):
                            bad.append((mode, prompt_type, app_online, active, origin))
    _check(not bad, "全部组合至少投递一端", f"{len(bad)} 个反例" if bad else "")


def print_matrix() -> None:
    """打印渠道决策矩阵。"""
    modes = [MODE_MIRROR_APP, MODE_PREFER_APP, MODE_PREFER_QQ, MODE_SMART]
    header = f"{'场景':32s}" + "".join(f"{m:>14s}" for m in modes)
    print()
    print("渠道决策矩阵（QQ+App / QQ / App / 无）")
    print(header)
    print("-" * len(header))
    for label, prompt_type, app_online, active in SCENARIOS:
        row = f"{label:32s}"
        for mode in modes:
            decision = decide_channel(
                sys_prompt_type=prompt_type,
                app_online=app_online,
                user_active_channel=active,
                mode=mode,
            )
            cell = ("QQ+App" if decision.deliver_qq and decision.deliver_app
                    else "QQ" if decision.deliver_qq
                    else "App" if decision.deliver_app
                    else "无")
            row += f"{cell:>14s}"
        print(row)
    print()
    print("提示：smart 的规则是「作息/健康类两端都发 → App 离线只发 QQ → "
          "用户在 QQ 只发 QQ → 用户在 App 只发 App → 判不出来就双投」。")
    print("      改动前等价于 mirror_app；想减少重复打扰通常选 smart。")


def report_message_types(day: str) -> None:
    """统计某天主动消息的类型分布，判断 smart 会影响哪些消息。"""
    log = PROJECT_ROOT / "logs" / day.replace("-", "/") / "active_care_messages.log"
    if not log.exists():
        print(f"\n[report] 未找到日志 {log}")
        return
    pattern = re.compile(r"已发送 ([a-z_]+) 消息")
    counter: Counter = Counter()
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if match:
            counter[match.group(1)] += 1
    print(f"\n[report] {day} 实际发出的主动消息类型分布（共 {sum(counter.values())} 条）")
    for name, count in counter.most_common():
        decision = decide_channel(
            sys_prompt_type=name,
            app_online=True,
            user_active_channel="qq",
            mode=MODE_SMART,
        )
        tag = "两端都发" if decision.rule == "always_both" else "只发一端"
        print(f"  {name:28s} {count:3d} 条   smart 下：{tag}（{decision.rule}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证主动关怀投递渠道策略")
    parser.add_argument("--report", metavar="YYYY-MM-DD", help="统计某天的消息类型分布")
    args = parser.parse_args()

    verify_wiring()
    verify_safety()
    print_matrix()
    if args.report:
        report_message_types(args.report)

    print()
    if FAILURES:
        print(f"验证未通过：{len(FAILURES)} 项失败")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("验证通过：渠道策略已接入且不存在丢消息的组合 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
