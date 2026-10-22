#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证安卓「发送流水线 / 导航」解耦结果与会话预览归属的收敛。

背景：
1. `ChatSendController.kt` 曾膨胀到 1100+ 行，把进程级运行状态、发送预检、
   SSE 流式状态机、气泡链、会话预览写入、回复通知全部塞在一个文件里。
2. `NavGraph.kt` 曾 697 行，七个业务域的 ViewModel 绑定、生命周期回调、
   深链与转场动画平铺在同一函数里。
3. 会话列表副标题串台（多个角色的预览变成同一段话）的根因，正是预览归属
   散落在三处、每处都带一层"解析不到就猜一个 persona"的兜底。

本脚本把解耦后的结构约束与归属唯一性固化成回归检查：
1. 两个入口文件都在 Kotlin 单文件上限内，且只做编排
2. 拆出的子文件都在约定目录里
3. 会话预览写入点收敛为「消息库重建 + 唯一 writer」
4. 「用本页 persona 兜底预览归属」的写法已消失
5. 拆分包内所有 Kotlin 文件括号配对、无未使用 import

运行：
    python3 tests/scripts/android_frontend/verify_chat_send_nav_decomposition.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# 行数档位不在本文件重复定义：`check_file_sizes.LIMITS` 是唯一定义处，
# 这里只取 Kotlin 档，避免规则一致性检查把 400 误判成 .py 的通用档。
sys.path.insert(0, str(ROOT / "tests" / "scripts" / "docs"))
from check_file_sizes import LIMITS  # noqa: E402

APP_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
CHAT_DIR = APP_MAIN / "presentation/chat"
SEND_DIR = CHAT_DIR / "send"
NAV_DIR = APP_MAIN / "presentation/navigation"
NAV_GRAPH_DIR = NAV_DIR / "graph"

NAV_GRAPH = NAV_DIR / "NavGraph.kt"
SEND_CONTROLLER = CHAT_DIR / "ChatSendController.kt"
META_REPOSITORY = APP_MAIN / "data/repository/PersonaLocalMetaRepository.kt"
INCOMING_HANDLER = CHAT_DIR / "ChatIncomingMessageHandler.kt"
CONVERSATION_VM = APP_MAIN / "presentation/conversations/ConversationListViewModel.kt"

MAX_KOTLIN_LINES = LIMITS[".kt"]

EXPECTED_SEND_FILES = (
    "AssistantBubbleChain.kt",
    "AssistantReplyFinalizer.kt",
    "AssistantReplyStreamer.kt",
    "ChatUiWriteGuard.kt",
    "ConversationPreviewWriter.kt",
    "ReplyOutcomeNotifier.kt",
    "SendPreflight.kt",
    "SendRuntime.kt",
)

EXPECTED_NAV_FILES = (
    "ChatGraph.kt",
    "ConversationsGraph.kt",
    "LifeGraph.kt",
    "MallGraph.kt",
    "NavTransitions.kt",
    "SettingsGraph.kt",
    "StudyGraph.kt",
    "WellbeingGraph.kt",
)

# 迁移到子文件后，入口里不应再出现这些私有实现符号
MOVED_OUT_OF_SEND_CONTROLLER = (
    "fun prepareSend(",
    "fun runAssistantGeneration(",
    "fun finalizeAssistantBubble(",
    "fun persistConversationPreview(",
    "fun notifyReplyAndBumpUnread(",
    "data class PreparedSend",
    "private val backgroundGenerationScope",
)

MOVED_OUT_OF_NAV_GRAPH = (
    "private fun RoleRow",
    "hiltViewModel()",
    "composable(",
)

# 会话预览允许的写入方：消息库重建 + 唯一 writer + 主动消息归档 + Room 回流补充
ALLOWED_PREVIEW_WRITERS = {
    "data/repository/PersonaLocalMetaRepository.kt",  # 定义处
    "presentation/chat/send/ConversationPreviewWriter.kt",
    "presentation/conversations/ConversationListViewModel.kt",
    "presentation/chat/ChatIncomingMessageHandler.kt",
    "services/foreground/ProactiveMessageHandler.kt",
}

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    """返回文件里未被引用的 import 行（粗粒度：按末段标识符整词匹配正文）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    body = "\n".join(
        line
        for line in lines
        if not line.startswith("import ") and not line.startswith("package ")
    )
    unused: list[str] = []
    for line in lines:
        if not line.startswith("import "):
            continue
        matched = IMPORT_RE.match(line)
        if not matched:
            continue
        if line.strip() in DELEGATE_IMPORTS:
            continue
        fq_name, alias = matched.group(1), matched.group(2)
        if fq_name.endswith("*"):
            continue
        name = alias or fq_name.rsplit(".", 1)[-1]
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            unused.append(line)
    return unused


def bracket_balance(path: Path) -> tuple[bool, str]:
    """粗粒度括号配对（忽略行注释与字符串字面量，足够抓住重构时的漏/多括号）。"""
    source = path.read_text(encoding="utf-8")
    # 去掉行注释与字符串内容，避免注释里的中文括号/花括号干扰
    stripped = re.sub(r'"""(?:.|\n)*?"""', '""', source)
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for ch in stripped:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False, f"{path.name}: 括号配对失败（多余或顺序错误的 {ch}）"
    if stack:
        return False, f"{path.name}: 括号未闭合 {stack[-1]}（剩余 {len(stack)} 层）"
    return True, f"{path.name}: 括号配对正常"


def kotlin_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.kt") if path.is_file())


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("发送流水线 / 导航解耦验证")
    print("=" * 70)

    # 1. 入口体积与职责
    for path in (SEND_CONTROLLER, NAV_GRAPH):
        count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"{path.name} 行数：{count}")
        results.append(
            _check(count <= MAX_KOTLIN_LINES, f"{path.name} {count} 行 <= {MAX_KOTLIN_LINES} 行")
        )

    send_source = SEND_CONTROLLER.read_text(encoding="utf-8")
    leftover = [symbol for symbol in MOVED_OUT_OF_SEND_CONTROLLER if symbol in send_source]
    results.append(_check(not leftover, f"ChatSendController 只做编排，残留实现：{leftover or '无'}"))

    nav_source = NAV_GRAPH.read_text(encoding="utf-8")
    leftover_nav = [symbol for symbol in MOVED_OUT_OF_NAV_GRAPH if symbol in nav_source]
    results.append(_check(not leftover_nav, f"NavGraph 只做编排，残留注册：{leftover_nav or '无'}"))

    # 2. 子文件齐全且都在上限内
    for directory, expected, label in (
        (SEND_DIR, EXPECTED_SEND_FILES, "send"),
        (NAV_GRAPH_DIR, EXPECTED_NAV_FILES, "navigation/graph"),
    ):
        missing = [name for name in expected if not (directory / name).exists()]
        results.append(_check(not missing, f"{label} 子文件齐全，缺失：{missing or '无'}"))
        oversized = [
            f"{path.name}={len(path.read_text(encoding='utf-8').splitlines())}"
            for path in kotlin_files(directory)
            if len(path.read_text(encoding="utf-8").splitlines()) > MAX_KOTLIN_LINES
        ]
        results.append(
            _check(not oversized, f"{label} 子文件都在 {MAX_KOTLIN_LINES} 行内，超限：{oversized or '无'}")
        )

    # 3. 会话预览写入方白名单
    actual_writers: set[str] = set()
    for path in APP_MAIN.rglob("*.kt"):
        text = path.read_text(encoding="utf-8")
        if "updateLastMessage(" in text and "suspend fun updateLastMessage(" not in text:
            actual_writers.add(path.relative_to(APP_MAIN).as_posix())
    unexpected = sorted(actual_writers - ALLOWED_PREVIEW_WRITERS)
    results.append(
        _check(
            not unexpected,
            "会话预览写入方收敛到白名单，越界："
            f"{unexpected or '无'}（实际：{sorted(actual_writers)}）",
        )
    )

    # 4. 不允许再出现"解析不到就用本页 persona"的预览兜底
    incoming = INCOMING_HANDLER.read_text(encoding="utf-8")
    results.append(
        _check(
            "getProfileFilename" not in incoming,
            "ChatIncomingMessageHandler 不再持有本页 persona 兜底",
        )
    )
    results.append(
        _check(
            "authoritative = true" in CONVERSATION_VM.read_text(encoding="utf-8"),
            "列表重建以消息库为准（authoritative）覆盖历史脏预览",
        )
    )
    meta_source = META_REPOSITORY.read_text(encoding="utf-8")
    results.append(
        _check(
            "authoritative: Boolean = false" in meta_source,
            "updateLastMessage 区分实时写入与权威重建",
        )
    )

    # 5. 括号配对 + 未使用 import
    checked = list(kotlin_files(SEND_DIR)) + list(kotlin_files(NAV_GRAPH_DIR))
    checked += [NAV_GRAPH, SEND_CONTROLLER, INCOMING_HANDLER, META_REPOSITORY, CONVERSATION_VM]
    for path in checked:
        ok, msg = bracket_balance(path)
        results.append((ok, msg))

    unused_report: list[str] = []
    for path in checked:
        for unused in find_unused_imports(path):
            unused_report.append(f"{path.name}: {unused}")
    results.append(
        _check(
            not unused_report,
            "涉及文件无未使用 import"
            + ("" if not unused_report else "，实际：\n    " + "\n    ".join(unused_report)),
        )
    )

    print("\n" + "-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：发送流水线与导航已解耦，会话预览归属单一。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
