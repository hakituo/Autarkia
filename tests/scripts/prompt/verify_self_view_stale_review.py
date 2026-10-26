"""验证主人卡月度过期审查（遗弃不删除）。

覆盖：
1. 候选收集：只审可过期类别（身份/设备/作息…），偏好类不进月审
2. stale 响应解析（剥围栏 + 提取条目）
3. 月审执行：过期事实被标记 stale，不再注入，但数据保留在档案中
4. 非月末跳过、月末触发
5. 过期标记不影响正常事实的注入

路径隔离：patch data_paths 的 self_view / pending 路径到临时目录。
LLM 用 Fake 类替换 PeopleProfileExtractor.call_llm，不真调模型。
"""

from __future__ import annotations

import asyncio
import datetime
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
    import core.utils.data.data_paths as data_paths

    data_paths.get_user_self_view_path = lambda scope: (tmp_dir / f"{scope}.json").resolve()
    data_paths.get_user_self_views_dir = lambda: tmp_dir.resolve()
    data_paths.get_user_self_views_pending_dir = lambda: (tmp_dir / "pending").resolve()
    data_paths.get_user_self_view_pending_path = lambda scope: (
        tmp_dir / "pending" / f"{scope}.jsonl"
    ).resolve()


class _FakeLLM:
    """替换 PeopleProfileExtractor.call_llm：固定返回过期判定。"""

    calls = 0
    prompts: list = []
    response = (
        '收到，判定如下：\n```json\n'
        '{"stale": [{"key": "学生身份", "value": "高中生，正在准备高考", "reason": "高考已结束"}]}'
        "\n```"
    )

    async def call_llm(self, prompt: str) -> str:
        _FakeLLM.calls += 1
        _FakeLLM.prompts.append(str(prompt))
        return _FakeLLM.response


async def _run_checks(tmp_dir: Path) -> None:
    from core.character.people import self_view_review as review
    from core.character.people import self_view_store as store
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people.models import KnownFact

    store.upsert_facts(
        "aveline",
        [
            KnownFact(key="学生身份", value="高中生，正在准备高考", confidence=0.99),
            KnownFact(key="学业状态", value="已结束高考，成绩尚未公布", confidence=0.99),
            KnownFact(key="设备", value="手机：iPhone 15", confidence=0.9),
            KnownFact(key="喜好", value="打羽毛球", confidence=0.9),
        ],
    )

    # ── 1. 候选分组：同类事实归同组（可对比），偏好类排除 ──
    profile = store.get_self_view("aveline")
    grouped = review._group_candidates(profile)
    _check(
        "身份" in grouped and "设备" in grouped,
        f"可过期类别按类分组（实际: {list(grouped)}）",
    )
    _check(len(grouped.get("身份", [])) == 2, "同类事实归入同组（身份类 2 条）")
    _check("偏好" not in grouped, "偏好类不进入月审（控制 prompt 预算）")

    # ── 2. stale 响应解析 ──
    parsed = review._parse_stale_response(
        '```json\n{"stale": [{"key": "a", "value": "b", "reason": "c"}]}\n```'
    )
    _check(len(parsed) == 1 and parsed[0]["key"] == "a", "围栏 JSON 解析出 stale 条目")
    _check(review._parse_stale_response("完全不是 JSON") == [], "非 JSON 返回空")

    # ── 3. 月审执行：标记过期 + 停止注入 + 数据保留 ──
    original = PeopleProfileExtractor.call_llm
    PeopleProfileExtractor.call_llm = _FakeLLM.call_llm
    try:
        marked = await review._review_one_scope("aveline", datetime.date(2026, 10, 31))
    finally:
        PeopleProfileExtractor.call_llm = original
    _check(marked == 1, f"过期事实被标记（实际标记 {marked} 条）")
    _check(
        any("正在准备高考" in p and "已结束高考" in p for p in _FakeLLM.prompts),
        "同类矛盾事实同批送审（LLM 可对比更改与合理性）",
    )

    rendered = store.render_self_view_injection("aveline")
    _check("正在准备高考" not in rendered, "过期事实不再注入 prompt")
    _check("iPhone 15" in rendered, "正常事实继续注入")
    _check("已结束高考" in rendered, "未判定过期的事实继续注入")

    saved = json.loads((tmp_dir / "aveline.json").read_text(encoding="utf-8"))
    raw_facts = saved.get("detailed", {}).get("known_facts", [])
    stale_facts = [f for f in raw_facts if f.get("status") == "stale"]
    _check(
        len(stale_facts) == 1 and "正在准备高考" in stale_facts[0].get("value", ""),
        "数据保留在档案中（遗弃不是删除）",
    )
    _check(
        bool(stale_facts[0].get("stale_reason") and stale_facts[0].get("staled_at")),
        "过期条目带原因与时间戳（可追溯）",
    )

    # ── 4. 非月末跳过、月末触发 ──
    _FakeLLM.calls = 0
    PeopleProfileExtractor.call_llm = _FakeLLM.call_llm
    try:
        await review.run_self_view_review({}, datetime.date(2026, 10, 23))
        _check(_FakeLLM.calls == 0, "非月末不触发审查")

        results: dict = {}
        await review.run_self_view_review(results, datetime.date(2026, 10, 31))
        _check(_FakeLLM.calls >= 1, "月末触发审查")
        _check(isinstance(results.get("self_view_review"), dict), "审查结果写入 nightly results")
    finally:
        PeopleProfileExtractor.call_llm = original


def main() -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="self_view_review_verify_"))
    _install_path_isolation(tmp_dir)
    try:
        asyncio.run(_run_checks(tmp_dir))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"\n=== 月审验证：{_PASS} 通过 / {_FAIL} 失败 ===")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
