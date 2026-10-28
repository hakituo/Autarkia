"""梗概自动注入的选取规则：分类挑选、去重、预算截断、渲染（纯函数，不读盘）。"""

from __future__ import annotations

from memory.notes.injection import selection as sel

NOW = 1_800_000_000.0
DAY = 86400.0


def _distinct(seed: int, length: int) -> str:
    """互不重叠的汉字串（二元组不相交），用来绕开去重测预算。"""
    start = 0x4E00 + seed * 1000
    return "".join(chr(start + i) for i in range(length))


def _note(note_id, kind, text, *, importance=0.5, ts=NOW - DAY):
    return {
        "note_id": note_id,
        "kind": kind,
        "text": text,
        "importance": importance,
        "occurred_from": ts,
        "occurred_to": ts + 600,
        "source_event_ids": [f"e_{note_id}"],
    }


def test_pick_plans_keeps_recent_window_newest_first():
    notes = [
        _note("p_old", "plan", "十五天前的计划", ts=NOW - 15 * DAY),
        _note("p1", "plan", "昨天定的计划", ts=NOW - DAY),
        _note("p2", "plan", "今天定的计划", ts=NOW - 600),
        _note("f1", "fact", "不是计划"),
    ]
    picked = sel.pick_plans(notes, NOW)
    assert [n["note_id"] for n in picked] == ["p2", "p1"]


def test_pick_preferences_sorts_by_importance_then_recency_without_threshold():
    notes = [
        _note("low", "preference", "一般偏好", importance=0.5),
        _note("hi_old", "preference", "重要偏好旧", importance=0.8, ts=NOW - 3 * DAY),
        _note("hi_new", "preference", "重要偏好新", importance=0.8, ts=NOW - DAY),
        _note("plan", "plan", "高重要度计划", importance=0.8),
    ]
    # 不设门槛：v8 短事实重要度全是 0.5，设门槛会让偏好栏永远空
    assert [n["note_id"] for n in sel.pick_preferences(notes)] == ["hi_new", "hi_old", "low"]


def test_pick_plans_drops_done_cancelled_and_plans_closed_later():
    trip = _note("trip", "plan", "阿明下周三去成都出差三天", ts=NOW - 3 * DAY)
    notes = [
        trip,
        dict(_note("trip_done", "plan", "阿明下周三去成都出差三天", ts=NOW - DAY), status="done"),
        dict(_note("gym", "plan", "周末去健身房办卡", ts=NOW - 2 * DAY), status="cancelled"),
        dict(_note("exam", "plan", "月底参加英语四级考试", ts=NOW - DAY), status="open"),
        _note("read", "plan", "这周读完那本小说", ts=NOW - 2 * DAY),
    ]
    assert [n["note_id"] for n in sel.pick_plans(notes, NOW)] == ["exam", "read"]


def test_plan_closer_before_the_plan_does_not_close_it():
    notes = [
        dict(_note("old_done", "plan", "阿明去成都出差三天", ts=NOW - 5 * DAY), status="done"),
        _note("again", "plan", "阿明又要去成都出差三天", ts=NOW - DAY),
    ]
    assert [n["note_id"] for n in sel.pick_plans(notes, NOW)] == ["again"]


def test_compose_respects_per_section_limits_in_priority_order():
    sections = {
        "relevant": [_note(f"r{i}", "episode", _distinct(i, 10)) for i in range(5)],
        "plan": [_note(f"p{i}", "plan", _distinct(10 + i, 10)) for i in range(4)],
        "preference": [_note(f"f{i}", "preference", _distinct(20 + i, 10)) for i in range(5)],
    }
    picked = sel.compose(sections, existing=[])
    by_section = [section for section, _note_, _text in picked]
    assert by_section == ["relevant"] * 5 + ["plan"] * 2 + ["preference"] * 3


def test_compose_clips_each_item_and_stops_at_total_budget():
    sections = {
        "relevant": [_note(f"r{i}", "episode", _distinct(i, 300)) for i in range(5)],
        "plan": [_note(f"p{i}", "plan", _distinct(10 + i, 300)) for i in range(2)],
        "preference": [_note(f"f{i}", "preference", _distinct(20 + i, 300)) for i in range(3)],
    }
    picked = sel.compose(sections, existing=[])
    lengths = {section: [] for section in ("relevant", "plan", "preference")}
    for section, _note_, text in picked:
        lengths[section].append(len(text))
    # 5×100 + 2×60 = 620，再装 3 条 60 的偏好 = 800，正好装满
    assert lengths["relevant"] == [100] * 5
    assert lengths["plan"] == [60, 60]
    assert lengths["preference"] == [60, 60, 60]
    assert sum(len(text) for _s, _n, text in picked) <= sel.TOTAL_CHARS
    assert all(text.endswith("…") for _s, _n, text in picked)


def test_compose_dedupes_by_id_text_and_existing_injections():
    shared = _note("same", "plan", "周五晚上一起去看电影")
    sections = {
        "relevant": [shared, _note("dup_text", "episode", "周五晚上一起去看电影")],
        "plan": [shared, _note("p2", "plan", "下周一交读书报告")],
        "preference": [_note("f1", "preference", "喜欢喝无糖的乌龙茶饮料", importance=0.8)],
    }
    existing = ["[10-20 10:00] 用户说自己喜欢喝无糖的乌龙茶饮料"]
    picked = sel.compose(sections, existing)
    ids = [note["note_id"] for _s, note, _t in picked]
    assert ids == ["same", "p2"]


def test_render_empty_is_empty_string():
    assert sel.render([]) == ""


def test_render_groups_sections_with_labels():
    picked = sel.compose(
        {
            "relevant": [_note("r1", "episode", "聊了期中考试复习安排")],
            "plan": [_note("p1", "plan", "周六去图书馆")],
            "preference": [_note("f1", "preference", "不吃香菜", importance=0.8)],
        },
        existing=[],
    )
    block = sel.render(picked)
    lines = block.split("\n")
    assert lines[0] == sel.HEADER
    assert lines[-1] == sel.FOOTER
    assert "相关：" in lines and "近期计划：" in lines and "偏好：" in lines
    assert any(line.startswith("- [梗概] [") and "期中考试" in line for line in lines)
    assert any(line.startswith("- [计划] [") and "图书馆" in line for line in lines)
    # 偏好不带时间；每行末尾带短编号，供回查原话兜底
    assert "- [偏好] 不吃香菜" in lines
    assert "expand_memory" in lines[-1]


def test_render_appends_short_note_ref_for_fallback():
    note = dict(_note("r1", "episode", "聊了期中考试"), note_id="note_" + "ab" * 12)
    block = sel.render(sel.compose({"relevant": [note]}, existing=[]))
    assert "聊了期中考试 #note_abababab" in block
