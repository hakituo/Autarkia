import json

import pytest

from core.agents.chat_agent_components.context_persona import select_message_tools
from core.agents.chat_agent_components.streaming_pipeline.dynamic_context import (
    FOOD_IMAGE_AUTO_RECORD_INSTRUCTION,
)
from core.services.health_sync import store
from core.tools.nutrition_log_tool import RecordNutritionFromImageTool


def test_food_image_route_selects_nutrition_writer():
    selected = select_message_tools(
        "[图片: /output/image/uploads/meal.jpg] （用户发送了一张图片）",
        profile_filename="core_aveline.json",
    )

    assert "record_nutrition_from_image" in selected


def test_food_image_instruction_requires_food_confirmation():
    """图片指令必须先要求判断是不是食物，再谈记录。"""
    assert "确认是食物" in FOOD_IMAGE_AUTO_RECORD_INSTRUCTION
    assert "image_is_food=true" in FOOD_IMAGE_AUTO_RECORD_INSTRUCTION
    assert FOOD_IMAGE_AUTO_RECORD_INSTRUCTION.index("先判断") < (
        FOOD_IMAGE_AUTO_RECORD_INSTRUCTION.index("record_nutrition_from_image")
    )


def _patch_nutrition_clock(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "get_companion_data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "today_str", lambda: "2026-10-15")
    monkeypatch.setattr(store, "now_iso", lambda: "2026-10-15T10:00:00+08:00")


def test_append_daily_nutrition_entries_saves_ai_estimates(monkeypatch, tmp_path):
    _patch_nutrition_clock(monkeypatch, tmp_path)
    entries = [
        {
            "id": "photo-item-1",
            "title": "鸡肉饭",
            "meal_type": "午餐",
            "calories": 620.0,
            "protein": 32.0,
            "source": "ai_photo_estimate",
            "is_estimated": True,
        }
    ]

    saved = store.append_daily_nutrition_entries(entries)
    daily = store.read_daily_nutrition("2026-10-15")

    expected = [
        {
            **entries[0],
            "date": "2026-10-15",
            "time": "2026-10-15T10:00:00+08:00",
        }
    ]
    assert saved == expected
    assert daily["nutrition_entries"] == expected
    assert daily["water_intake_entries"] == []


def test_append_daily_nutrition_entries_preserves_other_sources(monkeypatch, tmp_path):
    _patch_nutrition_clock(monkeypatch, tmp_path)
    nutrition_dir = store._nutrition_dir()
    path = nutrition_dir / "2026-10-15.json"
    existing_samsung_entry = {
        "title": "米饭",
        "time": "2026-10-15T10:00:00+08:00",
        "calories": 180.0,
    }
    existing_water_entry = {"time": "2026-10-15T09:00:00+08:00", "amount_ml": 250}
    path.write_text(
        json.dumps(
            {
                "nutrition_entries": [existing_samsung_entry],
                "water_intake_entries": [existing_water_entry],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_entry = {
        "id": "photo-item-2",
        "title": "米饭",
        "time": existing_samsung_entry["time"],
        "source": "ai_photo_estimate",
        "is_estimated": True,
        "calories": 200.0,
    }

    store.append_daily_nutrition_entries([ai_entry])
    daily = store.read_daily_nutrition("2026-10-15")

    assert daily["nutrition_entries"] == [
        existing_samsung_entry,
        {**ai_entry, "date": "2026-10-15"},
    ]
    assert daily["water_intake_entries"] == [existing_water_entry]


def _patch_tool_store(monkeypatch):
    recorded = []
    events = []
    monkeypatch.setattr(
        store, "append_daily_nutrition_entries", lambda entries: recorded.extend(entries) or entries
    )
    monkeypatch.setattr(
        store,
        "append_manual_event",
        lambda event_type, **fields: events.append({"type": event_type, **fields}),
    )
    return recorded, events


@pytest.mark.asyncio
async def test_photo_nutrition_tool_marks_estimates_and_appends_timeline(monkeypatch):
    recorded, events = _patch_tool_store(monkeypatch)
    food = {
        "title": "鸡肉饭",
        "portion": "一份",
        "calories": 620,
        "protein": 32,
        "data_basis": "estimate",
        "confidence": "medium",
    }

    result = await RecordNutritionFromImageTool()._run([food], meal_type="午餐", image_is_food=True)

    assert len(recorded) == 1
    assert recorded[0]["source"] == "ai_photo_estimate"
    assert recorded[0]["is_estimated"] is True
    assert recorded[0]["meal_type"] == "午餐"
    assert "估算值仅供参考" in result
    assert events[0]["type"] == "meal"
    assert events[0]["foods"] == ["鸡肉饭"]


@pytest.mark.asyncio
async def test_photo_nutrition_tool_writes_nothing_without_food_confirmation(monkeypatch):
    """模型没确认「图片里是食物」时一律不落盘。"""
    recorded, events = _patch_tool_store(monkeypatch)
    food = {"title": "鸡肉饭", "portion": "一份", "calories": 620}

    result = await RecordNutritionFromImageTool()._run([food], meal_type="午餐")

    assert recorded == []
    assert events == []
    assert "未记录" in result


@pytest.mark.asyncio
async def test_photo_nutrition_tool_drops_non_food_entries(monkeypatch):
    """图片描述当菜名 / 没有营养信息的条目被丢弃，正常食物照常写入。"""
    recorded, events = _patch_tool_store(monkeypatch)
    foods = [
        {"title": "用户私密部位照片", "portion": "一张特写照片", "calories": 0},
        {"title": "桌上的东西", "portion": "看不出份量", "calories": 0},
        {"title": "鸡肉饭", "portion": "一份", "calories": 620, "protein": 32},
    ]

    result = await RecordNutritionFromImageTool()._run(foods, image_is_food=True)

    assert [item["title"] for item in recorded] == ["鸡肉饭"]
    assert events[0]["foods"] == ["鸡肉饭"]
    assert "另有2项无法确认为食物" in result


@pytest.mark.asyncio
async def test_photo_nutrition_tool_writes_nothing_when_all_entries_rejected(monkeypatch):
    recorded, events = _patch_tool_store(monkeypatch)
    foods = [{"title": "聊天截图", "portion": "一张截图", "calories": 0}]

    result = await RecordNutritionFromImageTool()._run(foods, image_is_food=True)

    assert recorded == []
    assert events == []
    assert "未记录" in result


def test_id_keyed_photo_entry_does_not_collide_with_samsung_entry():
    shared_fields = {
        "title": "米饭",
        "time": "2026-10-15T10:00:00+08:00",
    }
    photo_entry = {
        **shared_fields,
        "id": "photo-item-3",
        "source": "ai_photo_estimate",
        "calories": 200.0,
    }
    samsung_entry = {**shared_fields, "calories": 180.0}

    merged = store._merge_entries([photo_entry], [samsung_entry], keys=("time", "title"))

    assert merged == [photo_entry, samsung_entry]
