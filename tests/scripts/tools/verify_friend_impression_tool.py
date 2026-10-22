"""验证Ye「记录朋友印象」工具（record_friend_impression）。

验证项：
1. 工具已注册，且发现元数据归类为 domain=friend_profile / risk_level=write。
2. 角色策略允许 ye 调用（roles.ye.resident）。
3. 新建：写入 <scope>/knowledge/people/<name>.json，字段形状与检索关键词齐全。
4. 二次记录：更新同一张卡，facts.impression 变化但 facts.relationship 保持。
5. 已有卡不被覆盖：命中身份匹配的作者卡，只加 facts.impression，不动 relationship。
6. 未注册 scope 拒绝写入。
7. 越界文件名被收敛在 people/ 内，不产生目录外文件。

运行：venv_cpu\\bin\\python tests/scripts/tools/verify_friend_impression_tool.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise AssertionError(msg)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_registration_and_metadata() -> None:
    print("[1] 工具注册与发现元数据...")
    from core.tools.friend_impression_tool import RecordFriendImpressionTool
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_metadata import build_tool_metadata
    from core.tools.tool_policy import resolve_role_tool_policy

    registry = ToolRegistry()
    register_all_tools(registry)
    tool = registry.get_tool("record_friend_impression")
    if tool is None:
        _fail("registry 中找不到 record_friend_impression")
    _ok("工具已注册")

    meta = build_tool_metadata(tool)
    if meta is None or meta.domain != "friend_profile" or meta.risk_level != "write":
        _fail(f"发现元数据不符: {meta}")
    _ok(f"元数据 domain={meta.domain} risk={meta.risk_level}")

    policy = resolve_role_tool_policy("core_ye.json")
    if not policy.allows("record_friend_impression"):
        _fail("ye 的角色策略未授权该工具")
    _ok("ye 常驻授权通过")

    if RecordFriendImpressionTool.name != "record_friend_impression":
        _fail("工具名不符")
    _ok("工具名正确")


async def _run_tool(tool, **kwargs) -> dict:
    tool.set_runtime_context(
        {
            "allowed_tool_names": ["record_friend_impression"],
            "profile_filename": "core_ye.json",
        }
    )
    return json.loads(await tool.run(**kwargs))


async def test_write_flow(tmp: Path) -> None:
    import core.tools.friend_impression_tool as fit

    tool = fit.RecordFriendImpressionTool()
    people_dir = tmp / "ye" / "knowledge" / "people"

    print("[2] 新建朋友印象卡...")
    result = await _run_tool(tool, name="林小雨", impression="隔壁实验室的师妹，话不多但很细心", aliases=["小雨"])
    if not result.get("ok") or not result.get("created"):
        _fail(f"新建失败: {result}")
    card_path = people_dir / "林小雨.json"
    if not card_path.is_file():
        _fail(f"未生成卡片文件: {card_path}")
    card = _read(card_path)
    checks = {
        "id": card.get("id") == "ye.person.林小雨",
        "topic": card.get("topic") == "person_林小雨",
        "projection": card.get("projection") == {"mode": "retrieval"},
        "identity": card["facts"]["identity"]["name"] == "林小雨",
        "aliases": "小雨" in card["facts"]["identity"].get("aliases", []),
        "impression": card["facts"].get("impression") == "隔壁实验室的师妹，话不多但很细心",
        "relationship": card["facts"].get("relationship") == "隔壁实验室的师妹，话不多但很细心",
        "keywords": set(card["retrieval"]["keywords"]) == {"林小雨", "小雨"},
        "modes": card["availability"]["interaction_modes"] == ["ordinary", "private"],
        "provenance": card["provenance"]["kind"] == "tool_recorded_friend_impression",
    }
    for name, passed in checks.items():
        if not passed:
            _fail(f"新建卡字段不符: {name} -> {card}")
    _ok("新建卡字段完整（id/topic/facts/retrieval/availability/provenance）")

    print("[3] 二次记录更新同一张卡...")
    files_before = sorted(p.name for p in people_dir.glob("*.json"))
    result2 = await _run_tool(tool, name="林小雨", impression="熟了之后发现她其实很爱吐槽", aliases=["小雨"])
    if result2.get("created") is not False:
        _fail(f"二次记录不应新建: {result2}")
    files_after = sorted(p.name for p in people_dir.glob("*.json"))
    if files_before != files_after:
        _fail(f"文件数量变化: {files_before} -> {files_after}")
    card2 = _read(card_path)
    if card2["facts"].get("impression") != "熟了之后发现她其实很爱吐槽":
        _fail("二次记录未更新 facts.impression")
    if card2["facts"].get("relationship") != "隔壁实验室的师妹，话不多但很细心":
        _fail("二次记录不应改动 facts.relationship")
    _ok("二次记录更新 impression 且保留 relationship")

    print("[4] 命中作者卡时不覆盖已有正文...")
    authored = people_dir / "xu_yan.json"
    authored.write_text(
        json.dumps(
            {
                "id": "ye.person.xu_yan",
                "topic": "person_xu_yan",
                "projection": {"mode": "retrieval"},
                "retrieval": {"keywords": ["许妍", "妍妍"]},
                "facts": {
                    "identity": {"name": "许妍", "aliases": ["妍妍"]},
                    "relationship": "作者写好的原关系",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    count_before = len(list(people_dir.glob("*.json")))
    result3 = await _run_tool(tool, name="许妍", impression="最近她带饭给我，人挺好", aliases=["妍宝"])
    if result3.get("created") is not False:
        _fail(f"命中作者卡不应新建: {result3}")
    if len(list(people_dir.glob("*.json"))) != count_before:
        _fail("命中作者卡却新增了文件")
    authored_card = _read(authored)
    if authored_card["facts"].get("relationship") != "作者写好的原关系":
        _fail("覆盖了作者写的 facts.relationship")
    if authored_card["facts"].get("impression") != "最近她带饭给我，人挺好":
        _fail("未写入工具自有的 facts.impression")
    if "妍宝" not in authored_card["retrieval"]["keywords"]:
        _fail("未合并新别名到 retrieval.keywords")
    _ok("作者卡只被追加 impression，正文与关系保持")

    print("[5] 未注册 scope 拒绝写入...")
    fit.get_registered_role_scopes = lambda: set()
    result4 = await _run_tool(tool, name="某人", impression="印象")
    if result4.get("ok") is not False:
        _fail(f"未注册 scope 应拒绝: {result4}")
    _ok("未知 scope 被拒绝")

    print("[6] 越界文件名被收敛...")
    fit.get_registered_role_scopes = lambda: {"ye"}
    result5 = await _run_tool(tool, name="../../evil", impression="越界测试")
    if not result5.get("ok"):
        _fail(f"越界名写入失败: {result5}")
    resolved = (people_dir / Path(result5["path"]).name).resolve()
    if not resolved.is_relative_to(people_dir.resolve()):
        _fail(f"落点越界: {resolved}")
    if list(tmp.glob("*.json")):
        _fail("产生了 people/ 之外的 json 文件")
    _ok("越界名被收敛在 people/ 内")


def test_knowledge_card_is_retrievable(tmp: Path) -> None:
    """端到端：新卡被角色资料的递归发现收录，并可按名字词面召回。"""
    print("[7] 新卡进入角色资料检索目录...")
    from core.agents.chat_agent_components.persona_system.prompt import context_engine as ce

    chunks = ce.load_chunks(tmp / "ye" / "knowledge")
    by_id = {chunk.id: chunk for chunk in chunks}
    chunk = by_id.get("ye.person.林小雨")
    if chunk is None:
        _fail(f"knowledge 递归发现未收录新卡: {sorted(by_id)}")
    if set(chunk.keywords) != {"林小雨", "小雨"}:
        _fail(f"检索关键词不符: {chunk.keywords}")
    if chunk.modes:
        recalled = ce.rank_chunks(chunks, "今天林小雨找我说话", chunk.modes[0])
        if not any(item.id == "ye.person.林小雨" for item in recalled):
            _fail("按名字做词面检索未召回新卡")
    _ok("新卡被 knowledge 发现且可被关键词召回")


async def _main() -> int:
    import core.tools.friend_impression_tool as fit

    tmp = Path(tempfile.mkdtemp(prefix="verify_friend_impression_"))
    try:
        original_root = fit._CONFIGS_ROOT
        original_scopes = fit.get_registered_role_scopes
        fit._CONFIGS_ROOT = tmp
        fit.get_registered_role_scopes = lambda: {"ye"}
        (tmp / "ye" / "knowledge" / "people").mkdir(parents=True, exist_ok=True)

        test_registration_and_metadata()
        await test_write_flow(tmp)
        test_knowledge_card_is_retrievable(tmp)
    finally:
        try:
            fit._CONFIGS_ROOT = original_root
            fit.get_registered_role_scopes = original_scopes
        except NameError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    people = tmp / "ye" / "knowledge" / "people"
    print("\nOK：新建 / 更新 / 作者卡保护 / 越界收敛 全部通过")
    print(f"（临时目录已清理；示例路径 {people}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
