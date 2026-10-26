"""根据用户主动发送的食物照片，保存逐项营养记录。"""

from __future__ import annotations

import asyncio
import uuid
from typing import List, Literal, Optional, Type

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.time_utils import now_iso, today_str

# 出现这些词说明 title/portion 描述的是「图片本身」，不是食物。模型偶尔会把
# 非食物图片（人物、截图、文档等）直接写成一条饮食记录，这里做兜底拦截。
# 注意不要收「胸」「脚」「嘴」这类会和菜名碰撞的字（鸡胸肉、猪脚饭、鸭嘴）。
_NON_FOOD_MARKERS = (
    "照片", "图片", "截图", "自拍", "画面", "表情包", "壁纸", "二维码",
    "文档", "表格", "聊天记录", "人像", "人物", "风景", "宠物", "漫画",
    "私密", "隐私", "裸", "生殖", "性器", "下体", "私处", "身体部位",
)

# 宏量营养素字段：用来判断这条记录到底有没有营养信息
_MACRO_FIELDS = ("protein", "carbs", "fat")


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
    image_is_food: bool = Field(
        False,
        description=(
            "先判断再填：当前图片里是否确实有用户要吃/喝的食物或饮品实物。"
            "确认是食物才填 true；人物、身体部位、聊天截图、文档、宠物、风景等一律 false，"
            "拿不准也填 false。false 时不会写入任何记录。"
        ),
    )
    foods: List[NutritionImageFoodInput] = Field(
        default_factory=list, max_length=12,
        description="图片中用户实际吃/喝的食物，可逐项拆分；图片不是食物时留空",
    )
    meal_type: Optional[str] = Field(
        None, description="早餐、午餐、晚餐或加餐；无法判断时留空"
    )


class RecordNutritionFromImageTool(BaseTool):
    name = "record_nutrition_from_image"
    description = (
        "记录用户发来的食物/饮品照片。先确认图片里确实有用户实际要吃/喝的实物，"
        "再把 image_is_food 填 true 并逐项识别内容与份量，按可见份量估算热量、蛋白质、碳水、脂肪；"
        "人物、身体部位、聊天截图、文档、宠物、风景等非食物图片一律不要调用，"
        "没有把握是食物时也不要为了凑记录去猜。"
        "title 只能是食物/饮品名称，禁止把照片内容本身（如「照片」「截图」「画面」）当菜名。"
        "微量营养素看不清或无法可靠估算时留空，不要编造精确数字。"
        "若包装营养标签清晰可读，按实际食用份量换算并将 data_basis 设为 nutrition_label；"
        "否则使用 estimate。保存的照片估算会明确标记为估算值。"
    )
    short_description = "把食物照片中的食物与估算营养保存到今日记录"
    category = "health"
    args_schema: Type[BaseModel] = RecordNutritionFromImageInput

    async def _run(
        self,
        foods: Optional[List[NutritionImageFoodInput]] = None,
        meal_type: Optional[str] = None,
        image_is_food: bool = False,
    ) -> str:
        # 先过「这是不是食物」这道门：没确认过食物一律不落盘，避免任意照片变成饮食记录
        if not image_is_food:
            return "未记录：当前图片不是食物或饮品，饮食记录没有写入。"

        candidates: List[NutritionImageFoodInput] = []
        skipped = 0
        for food in foods or []:
            parsed_food = (
                food if isinstance(food, NutritionImageFoodInput)
                else NutritionImageFoodInput.model_validate(food)
            )
            if _is_non_food_entry(parsed_food):
                skipped += 1
                continue
            candidates.append(parsed_food)

        if not candidates:
            return "未记录：图片里没有可确认的食物或饮品，饮食记录没有写入。"

        timestamp = now_iso()
        target_date = today_str()
        entries = []
        for parsed_food in candidates:
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
        skipped_text = f"（另有{skipped}项无法确认为食物，未记录）" if skipped else ""
        return (
            f"已保存{len(saved)}项饮食记录：{names}，合计约{total_calories:.0f} kcal"
            f"{basis_text}。{skipped_text}"
        )


def _is_non_food_entry(food: NutritionImageFoodInput) -> bool:
    """判断一条估算其实不是食物：把图片描述当菜名，或压根没有营养信息。

    Returns:
        True 表示应丢弃，不写入饮食记录。
    """
    title = str(food.title or "").strip()
    if not title:
        return True
    text = f"{title} {str(food.portion or '').strip()}"
    if any(marker in text for marker in _NON_FOOD_MARKERS):
        return True
    # 热量为 0 且蛋白质/碳水/脂肪全空：没有任何营养信息，不该占一条饮食记录
    if float(food.calories or 0) <= 0 and all(
        float(getattr(food, name) or 0) <= 0 for name in _MACRO_FIELDS
    ):
        return True
    return False


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
