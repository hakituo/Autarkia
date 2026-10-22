"""根据用户主动发送的食物照片，保存逐项营养记录。"""

from __future__ import annotations

import asyncio
import uuid
from typing import List, Literal, Optional, Type

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.time_utils import now_iso, today_str


class NutritionImageFoodInput(BaseModel):
    """照片中一份食物或饮品的营养估算。"""

    title: str = Field(..., min_length=1, description="食物或饮品名称")
    portion: str = Field(..., min_length=1, description="照片中可见的实际食用份量，如一碗、约200g")
    calories: float = Field(..., ge=0, description="该份量的热量 kcal")
    protein: Optional[float] = Field(None, ge=0, description="蛋白质 g")
    carbs: Optional[float] = Field(None, ge=0, description="碳水化合物 g")
    fat: Optional[float] = Field(None, ge=0, description="脂肪 g")
    saturated_fat: Optional[float] = Field(None, ge=0, description="饱和脂肪 g")
    trans_fat: Optional[float] = Field(None, ge=0, description="反式脂肪 g")
    monosaturated_fat: Optional[float] = Field(None, ge=0, description="单不饱和脂肪 g")
    polysaturated_fat: Optional[float] = Field(None, ge=0, description="多不饱和脂肪 g")
    dietary_fiber: Optional[float] = Field(None, ge=0, description="膳食纤维 g")
    sugar: Optional[float] = Field(None, ge=0, description="糖 g")
    cholesterol: Optional[float] = Field(None, ge=0, description="胆固醇 mg")
    sodium: Optional[float] = Field(None, ge=0, description="钠 mg")
    potassium: Optional[float] = Field(None, ge=0, description="钾 mg")
    vitamin_a: Optional[float] = Field(None, ge=0, description="维生素A μg")
    vitamin_c: Optional[float] = Field(None, ge=0, description="维生素C mg")
    calcium: Optional[float] = Field(None, ge=0, description="钙 mg")
    iron: Optional[float] = Field(None, ge=0, description="铁 mg")
    data_basis: Literal["estimate", "nutrition_label"] = Field(
        "estimate", description="estimate=按照片估算；nutrition_label=清晰可读的包装营养标签"
    )
    confidence: Literal["low", "medium", "high"] = Field(
        "medium", description="本条营养数据的可信度"
    )


class RecordNutritionFromImageInput(BaseModel):
    foods: List[NutritionImageFoodInput] = Field(
        ..., min_length=1, max_length=12,
        description="图片中用户实际吃/喝的食物，可逐项拆分",
    )
    meal_type: Optional[str] = Field(
        None, description="早餐、午餐、晚餐或加餐；无法判断时留空"
    )


class RecordNutritionFromImageTool(BaseTool):
    name = "record_nutrition_from_image"
    description = (
        "记录用户发来的食物/饮品照片。仅在当前对话确实附有食物图片时调用，"
        "逐项识别用户实际吃喝的内容和份量，按可见份量估算热量、蛋白质、碳水、脂肪；"
        "微量营养素看不清或无法可靠估算时留空，不要编造精确数字。"
        "若包装营养标签清晰可读，按实际食用份量换算并将 data_basis 设为 nutrition_label；"
        "否则使用 estimate。照片不是食物/饮品时不要调用。保存的照片估算会明确标记为估算值。"
    )
    short_description = "把食物照片中的食物与估算营养保存到今日记录"
    category = "health"
    args_schema: Type[BaseModel] = RecordNutritionFromImageInput

    async def _run(
        self,
        foods: List[NutritionImageFoodInput],
        meal_type: Optional[str] = None,
    ) -> str:
        if not foods:
            return "没有识别到可保存的食物项目。"

        timestamp = now_iso()
        target_date = today_str()
        entries = []
        for food in foods:
            parsed_food = (
                food if isinstance(food, NutritionImageFoodInput)
                else NutritionImageFoodInput.model_validate(food)
            )
            entry = parsed_food.model_dump(exclude_none=True)
            data_basis = entry.pop("data_basis", "estimate")
            confidence = entry.pop("confidence", "medium")
            entry.update(
                {
                    "id": uuid.uuid4().hex,
                    "title": str(entry.get("title") or "").strip(),
                    "meal_type": str(meal_type or "").strip() or None,
                    "time": timestamp,
                    "date": target_date,
                    "source": (
                        "ai_photo_label" if data_basis == "nutrition_label"
                        else "ai_photo_estimate"
                    ),
                    "is_estimated": data_basis != "nutrition_label",
                    "estimate_confidence": confidence,
                }
            )
            entries.append(entry)

        saved = await asyncio.to_thread(_persist_nutrition_entries, entries)
        total_calories = sum(float(item.get("calories") or 0) for item in saved)
        names = "、".join(str(item.get("title") or "食物") for item in saved)
        estimate_count = sum(1 for item in saved if item.get("is_estimated"))
        basis_text = "；其中照片估算值仅供参考" if estimate_count else "；营养数据来自包装标签"
        return (
            f"已保存{len(saved)}项饮食记录：{names}，合计约{total_calories:.0f} kcal"
            f"{basis_text}。"
        )


def _persist_nutrition_entries(entries: List[dict]) -> List[dict]:
    """同步写入每日条目和事件流；由线程池调用，避免阻塞对话事件循环。"""
    from core.services.health_sync.store import (
        append_daily_nutrition_entries,
        append_manual_event,
    )

    saved = append_daily_nutrition_entries(entries)
    if saved:
        append_manual_event(
            "meal",
            source="ai_photo",
            foods=[item.get("title") for item in saved if item.get("title")],
            delta_kcal=round(
                sum(float(item.get("calories") or 0) for item in saved), 1
            ),
            estimated=any(item.get("is_estimated") for item in saved),
            meal_type=next(
                (item.get("meal_type") for item in saved if item.get("meal_type")),
                None,
            ),
        )
    return saved
