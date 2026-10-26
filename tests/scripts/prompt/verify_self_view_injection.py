"""验证主人卡（self-view）全链路。

覆盖：
1. 存储读写与节流（upsert 同值跳过）
2. 分角色隔离（aveline / ling 各自独立）
3. 渲染注入（认知层 + 空档案返回空串）
4. 注入组件 scope 解析与标题包装
5. data.py static_part 挂载点存在
6. 实时捕获正则候选召回
7. 候选队列：只进 pending 不入库、重复去重、复核后消费清空
8. 夜间蒸馏 JSON 解析与置信度门槛
9. 注入优先级：硬事实优先于偏好类、偏好受每类限额

路径隔离：patch data_paths 的 self_view / pending 路径到临时目录，不碰真实 user_data。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))

_PASS = 0
_FAIL = 0


def _check(cond: bool, msg: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"[OK] {msg}")
    else:
        _FAIL += 1
        print(f"[FAIL] {msg}")


def _install_path_isolation(tmp_dir: Path) -> None:
    """把 self-view 路径重定向到临时目录（store 通过模块属性动态访问，patch 生效）。"""
    import core.utils.data.data_paths as data_paths

    data_paths.get_user_self_view_path = lambda scope: (tmp_dir / f"{scope}.json").resolve()
    data_paths.get_user_self_views_dir = lambda: tmp_dir.resolve()
    data_paths.get_user_self_views_pending_dir = lambda: (tmp_dir / "pending").resolve()
    data_paths.get_user_self_view_pending_path = lambda scope: (
        tmp_dir / "pending" / f"{scope}.jsonl"
    ).resolve()


def main() -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="self_view_verify_"))
    _install_path_isolation(tmp_dir)
    try:
        _run_all(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"\n=== 主人卡验证：{_PASS} 通过 / {_FAIL} 失败 ===")
    return 0 if _FAIL == 0 else 1


def _run_all(tmp_dir: Path) -> None:
    from core.character.people import self_view_store as store
    from core.character.people.models import KnownFact

    # ── 1. 存储读写 + 渲染 ──
    fact = KnownFact(key="设备", value="手机：iPhone 15", confidence=0.6, source="runtime_pattern")
    written = store.upsert_facts("aveline", [fact])
    _check(written is True, "upsert_facts 首次写入落盘")
    rendered = store.render_self_view_injection("aveline")
    _check("iPhone 15" in rendered, "渲染包含新写入的事实")
    _check("你了解的主人" in rendered, "渲染包含主人卡标题")

    # ── 2. 节流：同 key 同 value 跳过 ──
    again = store.upsert_facts(
        "aveline",
        [KnownFact(key="设备", value="手机：iPhone 15", confidence=0.6)],
    )
    _check(again is False, "同值重复写入被节流（不落盘）")

    # ── 3. 分角色隔离 ──
    store.upsert_facts(
        "aveline",
        [KnownFact(key="喜好", value="羽毛球", confidence=0.6, source="runtime_pattern")],
    )
    ling_rendered = store.render_self_view_injection("ling")
    _check("羽毛球" not in ling_rendered and "iPhone" not in ling_rendered,
           "ling 的渲染不含 aveline 的事实（分角色隔离）")
    aveline_rendered = store.render_self_view_injection("aveline")
    _check("羽毛球" in aveline_rendered, "aveline 渲染含其自身事实")
    saved_files = {p.name for p in tmp_dir.glob("*.json")}
    _check({"aveline.json"} == saved_files or saved_files == {"aveline.json"},
           f"分角色文件独立落盘（实际: {saved_files}）")

    # ── 4. 空档案：无认知层、无该 scope 文件 ──
    # SELF 客观层跨角色共享，真实环境下可能存在，所以空 scope 的渲染只可能
    # 出现【主人的基本资料】，绝不能出现认知层内容。
    empty_render = store.render_self_view_injection("nonexistent_scope_xyz")
    _check("你了解的主人" not in empty_render, "空档案不注入认知层标题")
    _check("羽毛球" not in empty_render and "iPhone" not in empty_render,
           "空档案不含其他角色的事实")

    # ── 5. 注入组件：scope 解析 + 标题包装 ──
    from core.agents.chat_agent_components.persona_system.prompt.components.self_view import (
        build_self_view_block,
        resolve_self_view_scope,
    )

    scope = resolve_self_view_scope("private_10001", "core_aveline.json")
    _check(scope == "aveline", f"profile_filename 优先解析 scope（实际: {scope}）")
    block = build_self_view_block("private_10001", "core_aveline.json")
    _check("你了解的主人" in block and "羽毛球" in block,
           "build_self_view_block 输出带标题的主人卡")

    # ── 6. data.py 挂载点存在 ──
    import inspect

    from core.agents.chat_agent_components.persona_system.prompt import data as prompt_data

    source = inspect.getsource(prompt_data.get_prompt_data)
    _check("build_self_view_block" in source, "get_prompt_data 已挂载主人卡注入")

    # ── 7. 实时捕获：正则提取 ──
    from core.character.people.self_view_capture import extract_facts_from_text

    pairs = dict(extract_facts_from_text("我的手机是iPhone 15，我喜欢打羽毛球，我今年23岁"))
    _check(pairs.get("设备") == "手机：iPhone 15", f"设备提取（实际: {pairs.get('设备')}）")
    _check(pairs.get("喜好") == "打羽毛球", f"喜好提取（实际: {pairs.get('喜好')}）")
    _check(pairs.get("年龄") == "23", f"年龄提取（实际: {pairs.get('年龄')}）")
    empty_pairs = extract_facts_from_text("今天天气真不错啊")
    _check(empty_pairs == [], "无关文本不产生事实")

    # ── 8. 捕获 hook：只进候选队列，绝不直接入库 ──
    from core.character.people.self_view_capture import capture_user_facts_async
    from core.utils.data import data_paths as _dp

    asyncio.run(capture_user_facts_async("private_10001", "我的生日是2001年5月3日", "core_aveline.json"))
    pending_path = _dp.get_user_self_view_pending_path("aveline")
    pending_items = [
        json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    _check(
        any(item.get("key") == "生日" and item.get("value") == "2001-05-03" for item in pending_items),
        f"候选写入 pending 队列（实际: {pending_items}）",
    )
    birthday = store.get_self_view("aveline")
    values = [f.value for f in (birthday.get_known_facts() if birthday else [])]
    _check("2001-05-03" not in values, "正则候选未直接入库（必须经 LLM 复核）")

    asyncio.run(capture_user_facts_async("private_10001", "我的生日是2001年5月3日", "core_aveline.json"))
    dup_count = len([ln for ln in pending_path.read_text(encoding="utf-8").splitlines() if ln.strip()])
    _check(dup_count == len(pending_items), f"重复候选去重（{len(pending_items)} → {dup_count}）")

    # ── 9. 候选复核链路：可读取 → 复核后消费清空 ──
    from core.character.people.self_view_distill import _consume_pending, _load_pending_candidates

    cands, total_lines = _load_pending_candidates("aveline")
    _check(
        any(c.get("key") == "生日" for c in cands) and total_lines >= 1,
        f"蒸馏可读到候选（{len(cands)} 条 / 队列 {total_lines} 行）",
    )
    _consume_pending("aveline", total_lines)
    _check(not pending_path.exists(), "复核完成后候选队列被消费清空")

    # ── 10. 夜间蒸馏 JSON 解析 ──
    from core.character.people.self_view_distill import _parse_facts_response

    parsed = _parse_facts_response(
        '好的，以下是提取结果：\n```json\n{"facts": [{"key": "所在城市", "value": "杭州", "confidence": 0.9}]}\n```'
    )
    _check(len(parsed) == 1 and parsed[0]["value"] == "杭州", "围栏 JSON 解析成功")
    _check(_parse_facts_response("完全不是 JSON") == [], "非 JSON 输入返回空")

    # ── 11. 置信度门槛 ──
    low = _parse_facts_response('{"facts": [{"key": "喜好", "value": "钓鱼", "confidence": 0.5}]}')
    _check(len(low) == 1, "低置信度条目可解析（门槛在入库侧过滤）")

    # ── 12. 注入优先级：硬事实优先于偏好类，且偏好受每类限额 ──
    prefs = [KnownFact(key=f"回复偏好{i}", value=f"偏好值{i}", confidence=1.0) for i in range(12)]
    store.upsert_facts("ling", prefs)
    store.upsert_facts(
        "ling",
        [
            KnownFact(key="设备", value="手机：iPhone 15", confidence=0.7),
            KnownFact(key="生日", value="2001-05-03", confidence=0.7),
        ],
    )
    ling_render = store.render_self_view_injection("ling")
    _check("iPhone 15" in ling_render, "硬事实（设备）优先于大量偏好类注入")
    _check("2001-05-03" in ling_render, "硬事实（生日）优先于大量偏好类注入")
    pref_lines = [ln for ln in ling_render.splitlines() if "回复偏好" in ln]
    _check(len(pref_lines) <= 2, f"偏好类受每类限额约束（实际 {len(pref_lines)} 条）")


if __name__ == "__main__":
    sys.exit(main())
