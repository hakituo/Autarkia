"""验证 QQ 收藏表情（NapCat mface）通道。

验证点：
1. `[FACE:wow]` 标签会被 extract_media_segments 解析成 face_labels 并从文本剥离
2. 收藏表情配置只对登记过的角色生成 prompt 说明（TT 有、ye 没有）
3. summary 匹配支持精确 / 包含 / 空白与方括号归一化
4. mface CQ 码字段完整，summary 做 CQ 安全转义
5. fetch_custom_face_detail 的两种返回形态都能取到条目
6. 角色无权限、收藏库里没有、字段不全时返回 None（不抛异常）
7. 解析结果按账号隔离缓存

运行：venv_cpu/bin/python tests/scripts/qq/verify_custom_face.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

_passed = 0


def _ok(msg: str):
    global _passed
    _passed += 1
    print(f"[PASS] {msg}")


def _fail(msg: str):
    print(f"[FAIL] {msg}")
    sys.exit(1)


from clients.bots.qq import custom_face
from clients.bots.qq.media_tags import extract_media_segments
from core.agents.chat_agent_components.persona_system.prompt.qq_integration import (
    build_custom_face_tag_prompt,
)

# 1. 标签解析
segments = extract_media_segments("哇！这也太离谱了[FACE:wow]")
labels = [lb for seg in segments for lb in seg.face_labels]
if labels != ["wow"]:
    _fail(f"[FACE:wow] 解析失败: {labels!r}")
if any("[FACE" in seg.text for seg in segments):
    _fail("标签没有被从文本里剥离")
_ok("[FACE:wow] 解析与剥离")

# 全角括号与冒号
segments = extract_media_segments("真的假的［FACE：wow］")
labels = [lb for seg in segments for lb in seg.face_labels]
if labels != ["wow"]:
    _fail(f"全角标签解析失败: {labels!r}")
_ok("全角 [FACE:xxx] 解析")

# 2. prompt 注入只对登记角色
tt_prompt = build_custom_face_tag_prompt("TT/core_TT.json")
if "[FACE:wow]" not in tt_prompt or "收藏表情" not in tt_prompt:
    _fail(f"TT 未注入收藏表情说明: {tt_prompt!r}")
if build_custom_face_tag_prompt("core_ye.json"):
    _fail("Ye不应注入 TT 的收藏表情说明")
_ok("prompt 注入按角色隔离")

# 3. summary 匹配
items = [
    {"md5": "aaa", "epId": "bbb", "resId": "ccc", "desc": "[哇]"},
    {"md5": "ddd", "epId": "eee", "resId": "fff", "desc": "笑死"},
]
if custom_face.match_emoji_item(items, "哇") is not items[0]:
    _fail("summary 包含匹配失败（[哇] 应命中 哇）")
if custom_face.match_emoji_item(items, "  【哇】 ") is not items[0]:
    _fail("summary 空白/方括号归一化失败")
if custom_face.match_emoji_item(items, "不存在") is not None:
    _fail("不存在的 summary 不应命中")
_ok("summary 匹配")

# 4. CQ 码构造与转义
cq = custom_face.build_mface_cq("aaa", "bbb", "ccc", "哇, [测]&试")
if not cq.startswith("[CQ:mface,emoji_id=aaa,emoji_package_id=bbb,key=ccc"):
    _fail(f"mface CQ 前缀错误: {cq}")
summary_value = cq.split("summary=", 1)[-1].rstrip("]")
for bad in (",", "[", "]", "&"):
    if bad in summary_value:
        _fail(f"summary 未转义字符 {bad!r}: {cq}")
_ok("mface CQ 构造与 summary 转义")

# 5. 两种返回形态
items_a = custom_face.extract_emoji_items({"data": {"emojiInfoList": items}})
items_b = custom_face.extract_emoji_items({"data": items})
if items_a != items or items_b != items:
    _fail(f"收藏表情返回形态解析失败: {items_a!r} / {items_b!r}")
_ok("fetch_custom_face_detail 返回形态兼容")

# 6. resolve 的各种拒绝路径
custom_face.clear_face_cache()


class _Caller:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def __call__(self, action, params=None, timeout_seconds=8.0):
        self.calls += 1
        return 0, {"data": {"emojiInfoList": self.items}}


async def _check_resolve():
    caller = _Caller(items)

    cq = await custom_face.resolve_custom_face(
        "wow", role_id="tt", account_key="ws://tt", call_action=caller
    )
    if not cq or "emoji_id=aaa" not in cq:
        _fail(f"TT 解析收藏表情失败: {cq!r}")

    # 缓存命中后不再调 NapCat
    calls_after_first = caller.calls
    await custom_face.resolve_custom_face(
        "wow", role_id="tt", account_key="ws://tt", call_action=caller
    )
    if caller.calls != calls_after_first:
        _fail("同一账号重复解析没有命中缓存")

    # 其他账号必须重新解析（字段按账号隔离）
    await custom_face.resolve_custom_face(
        "wow", role_id="tt", account_key="ws://other", call_action=caller
    )
    if caller.calls == calls_after_first:
        _fail("不同账号共用了收藏表情缓存")

    # 无权限角色
    denied = await custom_face.resolve_custom_face(
        "wow", role_id="ye", account_key="ws://ye", call_action=caller
    )
    if denied is not None:
        _fail("未登记角色不应能发 TT 的收藏表情")

    # 未登记的标签
    unknown = await custom_face.resolve_custom_face(
        "nope", role_id="tt", account_key="ws://tt", call_action=caller
    )
    if unknown is not None:
        _fail("未登记的收藏表情不应解析成功")

    # 收藏库里没有
    empty = await custom_face.resolve_custom_face(
        "wow", role_id="tt", account_key="ws://empty", call_action=_Caller([])
    )
    if empty is not None:
        _fail("收藏库里没有该表情时应返回 None")

    # 字段不全
    broken = await custom_face.resolve_custom_face(
        "wow",
        role_id="tt",
        account_key="ws://broken",
        call_action=_Caller([{"md5": "aaa", "desc": "哇"}]),
    )
    if broken is not None:
        _fail("字段不全时应返回 None")


asyncio.run(_check_resolve())
_ok("resolve 权限 / 缺字段 / 缓存隔离")

print(f"\n全部通过（{_passed} 组）")
