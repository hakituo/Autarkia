"""VL 打标提示词与输出解析。"""

from __future__ import annotations

import re
from typing import Any

# VL 询问 prompt（场景导向）
# 关键：让 VL 生成"使用场景"描述，而非纯客观画面描述，
# 这样 LLM 查询时（如 [MEME:被气到想打人]）才能语义匹配到对应的图
VL_PROMPT = (
    "你是表情包语义分析专家。这张表情包将用于语义检索——"
    "用户会用自然语言描述想表达的情绪/场景来搜索表情包。\n\n"
    "请分析图片并严格按以下格式输出（不要 markdown，不要多余解释）：\n\n"
    "CAPTION: <先简述画面（角色、动作、表情、画面文字），"
    "再用\"常在...时使用\"句式说明这张图适合的对话场景>\n"
    "TAGS: <3-8个关键词，顿号分隔，涵盖情绪、动作、使用场景>\n"
    "TEXT: <画面中的文字，无则写\"无\">\n\n"
    "示例：\n"
    "CAPTION: 卡通女仆张嘴伸手喊「别让我逮到你」，恼火中带玩笑的追打姿态。"
    "常在被对方气到、对方闯祸后用来抱怨算账，表示\"等着瞧\"的激烈反对。\n"
    "TAGS: 愤怒威胁、恼火追打、半开玩笑算账、抱怨反对、被气到\n"
    "TEXT: 别让我逮到你"
)

# VL 中转模型（SiliconFlow 已禁用 Qwen3-VL-235B-A22B-Thinking，改用 32B-Instruct）
VL_VISION_MODEL = "Qwen/Qwen3-VL-32B-Instruct"


def parse_vl_output(text: str) -> dict[str, Any] | None:
    """解析 VL 模型的三段式输出（CAPTION / TAGS / TEXT）。

    宽容匹配：不区分大小写、允许换行、允许字段缺失。
    """
    if not text or not text.strip():
        return None
    # CAPTION: 匹配到下一个大写字段标签或行尾
    cap_match = re.search(
        r"CAPTION\s*[:：]\s*(.*?)(?=\s*(?:TAGS|TEXT)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    tags_match = re.search(
        r"TAGS\s*[:：]\s*(.*?)(?=\s*(?:CAPTION|TEXT)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    text_match = re.search(
        r"TEXT\s*[:：]\s*(.*?)(?=\s*(?:CAPTION|TAGS)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    caption = cap_match.group(1).strip() if cap_match else ""
    tags_raw = tags_match.group(1).strip() if tags_match else ""
    visible_text = text_match.group(1).strip() if text_match else ""

    # 兜底：如果完全没匹配到 CAPTION 标签，整段当 caption（兼容旧 prompt 输出）
    if not caption and not tags_raw and not visible_text:
        caption = text.strip()

    # 解析 tags（顿号/逗号分隔）
    tags: list[str] = []
    if tags_raw:
        for t in re.split(r"[、,，]", tags_raw):
            t = t.strip()
            if t and t != "无":
                tags.append(t)

    # TEXT 写"无"时清空
    if visible_text in ("无", "none", "None", ""):
        visible_text = ""

    if not caption:
        return None
    return {"caption": caption, "tags": tags, "text": visible_text}
