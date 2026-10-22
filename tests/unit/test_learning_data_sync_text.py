"""文本类文件并集合并（月度蒸馏记忆）的单元测试。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.chat_merge import union_bytes  # noqa: E402
from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_PROJECT,
    GROUPS,
    MERGE_TEXT_RICHER,
    SyncItem,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.text_merge import union_text_richer  # noqa: E402

ITEM = SyncItem(
    "persona",
    BASE_PROJECT,
    "core/character/configs/extra/**/distilled_profile.md",
    merge=MERGE_TEXT_RICHER,
)

_REL = "core/character/configs/extra/2026/09/distilled_profile.md"


def _b(text: str) -> bytes:
    return text.encode("utf-8")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_persona_group_is_registered():
    assert "persona" in GROUPS
    assert {item.group for item in items_for(["persona"])} == {"persona"}


def test_union_text_richer_prefers_non_empty():
    """纯空白的一侧绝不能覆盖有实质内容的一侧。"""
    real = _b("# 2026-09 Distilled Memory\n\n### 用户核心特征更新\n- 作息长期昼夜颠倒\n")
    blank = _b("   \n\n")

    assert union_text_richer(blank, real) == real
    assert union_text_richer(real, blank) == real
    assert union_text_richer(b"", real) == real
    assert union_text_richer(real, b"") == real


def test_union_text_richer_prefers_more_content():
    """只有标题的空壳字符数更少，会被有实质内容的一侧胜过。"""
    shell = _b("# 2026-09 Distilled Memory\n\n")
    real = _b("# 2026-09 Distilled Memory\n\n### 用户核心特征更新\n- 作息长期昼夜颠倒\n")

    assert union_text_richer(shell, real) == real
    assert union_text_richer(real, shell) == real


def test_union_text_richer_is_order_independent_and_idempotent():
    a = _b("# 2026-09 Distilled Memory\n\n- 甲\n")
    b = _b("# 2026-09 Distilled Memory\n\n- 乙\n- 丙\n")
    c = _b("# 2026-09 Distilled Memory\n\n- 丁\n")

    first = union_text_richer(union_text_richer(a, b), c)
    second = union_text_richer(union_text_richer(c, b), a)
    assert first == second
    assert union_text_richer(first, first) == first


def test_union_bytes_dispatches_text_richer():
    assert union_bytes(MERGE_TEXT_RICHER, _b("短"), _b("更长的一份")) == _b("更长的一份")
    assert union_bytes("unknown-mode", b"a", b"b") is None


def test_scan_matches_only_distilled_profile(tmp_path):
    """persona 分组只捞 distilled_profile.md，同目录的 json 不进来。"""
    root = tmp_path / "repo"
    _write(root / _REL, "# 2026-09\n\n内容\n")
    _write(root / "core/character/configs/extra/2026/01/legacy.json", "{}")
    _write(root / "core/character/configs/extra/reference_examples.json", "{}")

    found = scan((ITEM,), {BASE_PROJECT: root}.get)

    assert set(found) == {f"{BASE_PROJECT}:{_REL}"}
