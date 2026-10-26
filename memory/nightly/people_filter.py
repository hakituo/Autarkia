"""人物线索的确定性过滤与零 API 本地信号（A5b / B2）。

从 ``distillation_codec`` 拆出：这里只做"谁能当人物线索"的判定，
不负责解析 LLM 响应格式。判定全部可解释：
- 对话双方本人（角色名/别名/role_id/用户显示名）一律剔除；
- 同名第三方带关系前缀时保留（「同学Ling」≠「Ling」）；
- 短文本走保守正则补线索，不调 LLM。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.services.dual_role.personas import get_persona
from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")

_EMPTY_MENTION_VALUES = {"无", "none", "null", "nil", "没有", "无人物", "无更新"}
#: 只表示"说话者自己"的写法：单独出现时不是人物线索
_SELF_ONLY_MENTIONS = frozenset({"我", "本人", "自己", "我本人", "我自己", "咱", "俺"})
#: 泛指对话者、不构成新人物的称呼
_GENERIC_PARTNER_NAMES = frozenset({"用户", "对方", "你", "您", "主人"})
#: 括号里写"我/本人"的自我标注，例如「Aveline（我）」
_SELF_ANNOTATION = re.compile(r"[（(【\[]\s*(?:我|本人|自己)\s*[）)】\]]")
_MENTION_TRIM = " \t\r\n\"'“”‘’[]【】（）()、,，.;；"


def _is_self_speaker(role: str) -> bool:
    """说话者是否指向角色本人：assistant 或任一已注册 role_id。

    历史实现写死 aveline / ling，Ye等其他角色的偏好永远进不了角色演化线索；
    这里改用角色注册表判断，新增角色无需再改本文件。
    """
    token = str(role or "").strip().lower()
    return token == "assistant" or get_persona(token) is not None


def _mention_key(value: Any) -> str:
    """同名判定键：去掉全部空白并忽略大小写，不做子串/别名扩展。"""
    return re.sub(r"\s+", "", str(value or "")).casefold()


def empty_profile_signals(*, analyzed: bool) -> Dict[str, Any]:
    """构造蒸馏阶段的人物门控元数据。"""
    return {
        "profile_signal_version": 1,
        "profile_signal_analyzed": analyzed,
        "people_mentions": [],
        "role_update_candidates": [],
    }


def build_excluded_people_names(perspective: Optional[Dict[str, str]] = None) -> List[str]:
    """对话双方本人的名字：提示词要求模型别把对话者当人物线索。

    prompt 只是软约束；这里给出确定性名单，由 ``filter_people_mentions``
    在解析后统一剔除。名单包含角色自己的中文名/英文名/别名/role_id 与
    对话者显示名 —— 认不出角色时返回泛指名单（不猜默认角色）。
    """
    names: List[str] = []

    def _push(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)

    view = perspective or {}
    role_id = str(view.get("role_id") or "").strip()
    _push(view.get("role_name"))
    _push(role_id)
    profile = get_persona(role_id) if role_id else None
    if profile is not None:
        _push(getattr(profile, "cn_name", ""))
        _push(getattr(profile, "en_name", ""))
        for alias in getattr(profile, "aliases", ()) or ():
            _push(alias)
    _push(view.get("user_name"))
    for generic in _GENERIC_PARTNER_NAMES:
        _push(generic)
    return names


def filter_people_mentions(
    values: List[str],
    excluded_names: Optional[List[str]] = None,
) -> List[str]:
    """剔除指向对话者本人的"人物线索"，保留真正的第三方。

    判定只用可解释的确定性规则，不做语义猜测：
    - 值本身是"我/本人/自己"这类自称 → 丢弃；
    - 去掉「（我）」这类自我标注后与排除名单同名 → 丢弃；
    - 与前缀/关系描述组合的（如「我的同学小明」「同学Ling」）→ 保留，
      同名第三方因此不会被误删；
    - 互识角色、未知角色不在排除名单里 → 原样保留。

    比较只做「去空白 + 忽略大小写」的严格同名判断：``normalize_persona_name``
    会把包含角色名的长串也归一化过去，用它判等会把「同学Aveline」误删。
    """
    excluded = {
        _mention_key(name) for name in (excluded_names or []) if str(name or "").strip()
    }
    filtered: List[str] = []
    for raw in values or []:
        # 先去自我标注再去首尾标点：先 strip 会把「自己（我）」的右括号削掉，
        # 导致标注正则匹配不上。
        core = _SELF_ANNOTATION.sub("", str(raw or ""))
        value = core.strip(_MENTION_TRIM)
        if not value or value.casefold() in _EMPTY_MENTION_VALUES:
            continue
        if value in _SELF_ONLY_MENTIONS:
            continue
        if _mention_key(value) in excluded:
            continue
        if value not in filtered:
            filtered.append(value)
    return filtered


def filter_profile_signals(
    metadata: Dict[str, Any],
    perspective: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """在蒸馏元数据落盘前统一过滤人物线索。"""
    if not isinstance(metadata, dict):
        return empty_profile_signals(analyzed=False)
    filtered = dict(metadata)
    filtered["people_mentions"] = filter_people_mentions(
        list(metadata.get("people_mentions") or []),
        build_excluded_people_names(perspective),
    )
    return filtered


def detect_profile_signals_locally(
    content: str,
    *,
    role: str = "",
    owner_role_id: str = "",
) -> Dict[str, Any]:
    """短文本不调 LLM，用保守规则补齐人物门控元数据。"""
    metadata = empty_profile_signals(analyzed=True)
    text = str(content or "").strip()
    if not text:
        return metadata
    person_pattern = re.compile(
        r"(?:我的|他的|她的|家里的|班上的)?"
        r"(?:妈妈|爸爸|父亲|母亲|哥哥|弟弟|姐姐|妹妹|"
        r"老师|同学|朋友|同事|亲戚|室友|班主任|教授|医生|"
        r"师傅|老板|邻居|叔叔|阿姨|爷爷|奶奶|"
        r"外公|外婆|男朋友|女朋友)"
        r"|(?:叫|名叫|姓)\s*[\u4e00-\u9fff]{1,4}"
    )
    if person_pattern.search(text):
        metadata["people_mentions"] = ["local_candidate"]
    normalized_role = str(role or "").strip().lower()
    if _is_self_speaker(normalized_role) and re.search(
        r"(?:我|本人).{0,6}(?:喜欢|讨厌|不喜欢|习惯|偏好|"
        r"以后都|从不|总是|害怕|擅长|想要)",
        text,
    ):
        metadata["role_update_candidates"] = [owner_role_id or normalized_role]
    return metadata
