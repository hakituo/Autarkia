"""prompt 拼装解耦的护栏：快照对比，证明重构前后产物完全一致。

用法：
    # 重构前存基线
    python tests/scripts/prompt/verify_prompt_decoupling.py --save
    # 重构后比对
    python tests/scripts/prompt/verify_prompt_decoupling.py

快照写到 tests/scripts/prompt/_golden/<persona>.json，比对时逐条消息
逐字符比较；任何差异都会明确指出第几条消息从哪里开始不同。

另外顺带做重复注入检测：统计末尾 user 消息里各标记块出现的次数，
同一标记出现两次即为疑似重复（学习/教学、日期、日程这类容易重复注入）。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys
from contextlib import ExitStack
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _skip_data_dir_migration() -> None:
    """短路 companion_data 的初始化迁移。

    迁移在 import 期由 data_paths._ensure_initialized 触发，且会无条件重写
    companion_data 下的历史 jsonl；只读或受限环境里这一步直接抛 PermissionError，
    把与它无关的 prompt 快照比对整个带崩。本脚本只读配置与装配结果。
    """
    from core.utils.data import data_paths

    data_paths._INITIALIZED = True


_skip_data_dir_migration()

GOLDEN_DIR = Path(__file__).resolve().parent / "_golden"

PERSONA_FILES = {
    "aveline": "core_aveline.json",
    "ling": "core_ling.json",
    "ye": "core_ye.json",
    "lin": "core_lin.json",
    "tt": "TT/core_TT.json",
}

# 非【】形式的标记，单独计数；【】块头统一由正则扫描，避免重复计数
DUPLICATE_MARKERS = (
    "当前时间",
    "<system-reminder>",
)


class _FakeAgent:
    """够用的 agent 替身：拼装只读这几个属性，不触网、不启服务。"""

    tool_registry = None
    config = None

    def _is_study_mode(self, message, model_hint=None) -> bool:
        return False


# 时间相关注入每次跑都变，必须冻结才能做快照对比
FIXED_NOW = datetime(2026, 9, 19, 12, 0, 0)
_TIME_PATCHES = (
    "core.utils.time_utils.get_current_time",
    "core.utils.time.time_utils.get_current_time",
)
_SPECIAL_DAYS_DATE = (
    "core.agents.chat_agent_components.persona_system.prompt.special_days.date"
)


class _FrozenDate(date):
    """``special_days`` 直接调 ``date.today()``，只打 time_utils 补丁冻不住日历锚点。

    不冻结的话，快照里的「当前公历日期」每天都会变，基线隔天必然报不一致。
    """

    @classmethod
    def today(cls) -> "_FrozenDate":
        return cls(FIXED_NOW.year, FIXED_NOW.month, FIXED_NOW.day)


# CURRENT STATE 逐轮读 companion_data 的运行态；不冻结的话，角色换活动、换衣服都会让
# 快照报「拼装不一致」，把数据漂移误判成回归。快照又要提交进仓库，冻结成中性文案
# 同时也避免把真实运行态（含私密状态描述）写进 git，见 RULES.md §6。
FROZEN_RUNTIME_STATE = {
    "character": "snapshot",
    "schema_version": "2.0",
    "updated_at": "2026-09-19T12:00:00",
    "state": {
        "location": {
            "value": "宿舍",
            "source": "llm_tool",
            "updated_at": "2026-09-19T12:00:00",
            "confidence": None,
        },
        "activity": {
            "value": "在书桌前看书",
            "source": "llm_tool",
            "updated_at": "2026-09-19T12:00:00",
            "confidence": None,
        },
        "clothing": {
            "value": "白色上衣、灰色长裤",
            "source": "llm_tool",
            "updated_at": "2026-09-19T12:00:00",
            "confidence": None,
        },
        "people_present": {
            "value": "室友在",
            "source": "llm_tool",
            "updated_at": "2026-09-19T12:00:00",
            "confidence": None,
        },
    },
}


def build(profile_filename: str, *, freeze_time: bool = True) -> list[dict]:
    """拼一条完整消息列表。

    freeze_time=True：给快照用的，必须完全冻结才能逐字节比对；
    freeze_time=False：给重复注入扫描用的 —— 冻结时间会让 daily manager 的
    时间运算炸掉（naive/aware 相减），整段活动上下文消失，扫不出真实重复。
    """
    from core.agents.chat_agent_components.persona_system.prompt import (
        assembler,
        dynamic_injections,
    )

    with ExitStack() as stack:
        if freeze_time:
            for target in _TIME_PATCHES:
                try:
                    stack.enter_context(patch(target, return_value=FIXED_NOW))
                except (ModuleNotFoundError, AttributeError):
                    pass
            try:
                stack.enter_context(patch(_SPECIAL_DAYS_DATE, _FrozenDate))
            except (ModuleNotFoundError, AttributeError):
                pass
        # 「距上次对话」和「硬件状态」逐轮都变，快照必须冻结。
        # 调用点解耦前在 assembler 命名空间、解耦后在 dynamic_injections，补丁打在新家。
        # 只在 freeze_time 时冻：冻结的假块不含【角色睡眠状态】，会把真实块挡在扫描之外。
        if freeze_time:
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "build_time_context",
                    return_value="距上次对话：7小时23分钟",
                )
            )
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "get_cached_bionic_state",
                    return_value="你的硬件状态：CPU10% RAM66%",
                )
            )
            # 饱腹/口渴会随时间衰减（实测 1.5 小时掉了 4 点），不冻结基线必然漂移。
            # 护栏比的是拼装结构与顺序，业务数值的漂移必须排除在外。
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "build_food_context",
                    return_value=(
                        "【角色饮食状态】\nhunger=80/100 (一般)\n"
                        "thirst=56/100\nenergy=100/100\nfood_inventory_count=0"
                    ),
                )
            )
            # 只拦 current_state.json；episodic / semantic 记忆仍读真实数据。
            try:
                from core.agents.chat_agent_components.persona_system.prompt import (
                    layered_context,
                )

                _real_loader = layered_context._load_runtime_json

                def _frozen_runtime_json(path, _loader=_real_loader):
                    if Path(path).name == "current_state.json":
                        return FROZEN_RUNTIME_STATE
                    return _loader(path)

                stack.enter_context(
                    patch.object(
                        layered_context, "_load_runtime_json", _frozen_runtime_json
                    )
                )
            except (ModuleNotFoundError, AttributeError):
                pass
        return assembler.build_complete_message_list(
            agent=_FakeAgent(),
            # 会话 id 跟着人设文件走：多角色快照各用各自的用户名，
            # 避免 TT 快照实际按 aveline 的用户资料拼装（现有四个角色取值不变）。
            user_id=f"shared__persona__{Path(profile_filename).stem}",
            message="今天吃了什么，昨天那件事还记得吗",
            user_name="测试用户",
            history_messages=[
                {"role": "user", "content": "早"},
                {"role": "assistant", "content": "早呀"},
            ],
            profile_filename=profile_filename,
            active_tools=["search_chat_history", "web_search"],
        )


def _diff(before: list[dict], after: list[dict]) -> list[str]:
    problems = []
    if len(before) != len(after):
        problems.append(f"消息条数不同: {len(before)} -> {len(after)}")
    for index, (old, new) in enumerate(zip(before, after)):
        if old == new:
            continue
        if old.get("role") != new.get("role"):
            problems.append(f"第{index}条 role 不同: {old.get('role')} -> {new.get('role')}")
            continue
        o, n = old.get("content", ""), new.get("content", "")
        if o == n:
            continue
        offset = next(
            (i for i, (a, b) in enumerate(zip(o, n)) if a != b), min(len(o), len(n))
        )
        problems.append(
            f"第{index}条内容不同（首个差异 @{offset}）：\n"
            f"    旧: ...{o[max(0, offset-40):offset+40]}...\n"
            f"    新: ...{n[max(0, offset-40):offset+40]}..."
        )
    return problems


def check_duplicates(messages: list[dict]) -> list[str]:
    """扫描整条 prompt 里所有【块头】/ system-reminder，出现两次即疑似重复注入。

    只算**行首**的【】：正文里也可能提到某个块名（例如 user_bio 那句
    "作息以【角色睡眠状态】【角色当前活动背景】为准"），那是引用不是注入，
    算进去会误报。
    """
    if not messages:
        return []
    text = "\n".join(str(item.get("content", "")) for item in messages)
    counter: dict[str, int] = {}
    for marker in DUPLICATE_MARKERS:
        counter[marker] = text.count(marker)
    for header in re.findall(r"(?m)^【[^】\n]{1,20}】", text):
        counter[header] = counter.get(header, 0) + 1
    found = [f"{name} ×{count}" for name, count in counter.items() if count >= 2]
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="覆盖写入基线快照")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        help="只处理指定角色（多 agent 并行时避免把别人未验证的改动写进基线）",
    )
    args = parser.parse_args()

    target_files = PERSONA_FILES
    if args.only:
        unknown = [name for name in args.only if name not in PERSONA_FILES]
        if unknown:
            parser.error(f"未知角色: {', '.join(unknown)}；可选: {', '.join(PERSONA_FILES)}")
        target_files = {name: PERSONA_FILES[name] for name in args.only}

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    if args.save:
        for name, filename in target_files.items():
            try:
                messages = build(filename)
            except Exception as exc:  # noqa: BLE001
                print(f"  [SKIP] {name}: 构建失败 {exc}")
                continue
            (GOLDEN_DIR / f"{name}.json").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [SAVED] {name}: {len(messages)} 条消息")
        print("基线快照已写入", GOLDEN_DIR)
        return

    failed = 0
    for name, filename in target_files.items():
        golden_path = GOLDEN_DIR / f"{name}.json"
        if not golden_path.exists():
            print(f"  [SKIP] {name}: 无基线快照")
            continue
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        current = build(filename)
        problems = _diff(golden, current)
        if problems:
            failed += 1
            print(f"  [FAIL] {name}:")
            for item in problems:
                print(f"      {item}")
        else:
            print(f"  [PASS] {name}: 与基线完全一致")

        dupes = check_duplicates(build(filename, freeze_time=False))
        print(f"      重复注入扫描: {'; '.join(dupes) if dupes else '无'}")

    print("\n结果:", "全部一致" if not failed else f"{failed} 个角色不一致")


if __name__ == "__main__":
    main()
