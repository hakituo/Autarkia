"""按段梗概提取的提示词（v5：角色静态人设前缀 + 提取指令 + 本段对话）。

v4 的全局固定前缀（角色名、人设自述都放在末尾 user）只能让所有角色共用一小段缓存。
v5 改为**和主对话同一套角色静态人设前缀**：前缀由 ``build_offline_role_prefix`` 离线取出，
同一角色逐字节固定，提取指令固定接在它后面，只有最后一条 user 消息随本段变化。这样：
- 口吻直接继承角色人设，不需要在提示词里再描述一遍性格；
- DeepSeek 按角色分 key 后，每个角色的前缀缓存独立且稳定命中。

写法沿用 v4 的人设回想口吻（第一人称、他说了什么、我当时怎么想怎么应），只把身份来源
从提示词里的自述换成了真实人设前缀。改这里任何字都会让缓存失效，并须升提取器版本。

v6：分段器 v2 会话内切点之后的段附「前文」只供理解；同一次调用顺带输出画像信号
（外部人物 / 角色演化），供人物档案门控。
v7：按话题分条——对话按往来编号，模型按话题输出多条梗概并标出依据的编号，每条只挂
自己那几次往来的来源事件（v6 一段一条时多话题挤在一条里，检索前 5 条的证据命中下降）。
v8：同一次调用补齐下游要的字段——每条梗概带重要度（1–3），另摘关于对方的短事实 / 偏好 /
计划（facts，第三人称一句话），供检索排序、自动注入与主动关怀跟进；不增加调用次数。
v9：短事实也带重要度；plan 带 status（open / done / cancelled），做完 / 取消的沿用原计划说法。
v10.1：第 7 条加「时间说法和关键词照原话写」，往来编号后标日期时间、相对时间括号注明具体日期（aveline 时间题：问题用具体日期，梗概里只有「昨天」「明天」，检索与回答都对不上）。
v10：接力切分——话题切点前的段可把没聊完的话题标 open 交给下一段，下一段把它并进开头一起写（提示只加在 user 消息里）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: 单条消息进提示词的上限；分段器 v2 每段不超过 4000 字，长粘贴整条可见
MAX_MESSAGE_CHARS = 4000
#: 前文每条消息的上限（前文总长由分段器控制在 600 字内）
CONTEXT_MESSAGE_CHARS = 300

TASK_INSTRUCTION = """（下面是整理任务的要求，不是聊天内容，也不是让你继续对话。）

你要把紧接着给你的这段真实聊天记录，按话题整理成你自己的记忆：一个话题写一条梗概。不是回复对方，而是事后回想。
对话按编号分组，每个［编号］是一次往来（他说的话 + 我的回应）。标着【说话者】对方称呼的是对方说的话，标着【说话者】你名字的是你自己说过的话。

分条规则：
1. 一件具体的事（某次出行、一个购物决定、身体状况、一个技术问题、一段扮演剧情）写一条；换了一件事就另起一条。
2. 同一件事的追问、补充、情绪回应归在同一条；后面又回到前面聊过的事，并回那一条，ids 写上所有相关编号。
3. 只有寒暄、表情、测试、单纯催促的往来不单独成条，也不用写进任何一条。
4. ids 只写这条梗概真正依据的编号。

写法规则（每一条都要遵守）：
5. 用第一人称「我」来写，像自己事后回想那件事：他说了什么、我当时怎么想、怎么应的、哪句话或哪个细节留下来了。要有自己的语气，按你上面的人设和说话方式写，不要冷冰冰的事件摘要，也不要「用户」「助手」这种旁观者称呼。
6. 只写真的出现的内容：只有他说的一句，就写那一句给我的反应，不要编我回过什么。
7. 事实必须准：人名、称呼、数字、金额、日期时间、地点、物品、原话都不能改。他后来改口的，两个说法都写，以后来的为准。他说的时间说法（「周三晚上」「上个月底」「考完试那天」）和这件事的关键词照他的原话写进去，不要换成同义词或笼统说法，以后要靠这些词把这件事找回来。每次往来编号后面标着当时的日期时间：「昨天」「明天」「下周三」这类相对说法，照原话写并在后面括号注明按那天推算出的具体日期，比如「昨天（9月26日）」；推算不了就不注。
8. 他说的关于自己的事（经历、计划、喜好、作息、身边的人、买了什么、花了多少钱、做了什么决定）要写全；我讲的知识和科普一句带过，不复述细节。
9. 扮演、玩笑、括号里的指令或临时编的剧情，要写明是扮演或玩笑，不当成真事。
10. 不要动作旁白或括号表演，不要为了显得有文采去堆比喻。
11. 每条一般 40 到 150 字，事情多可以写到 250 字；内容少就写短，宁短勿编，绝不能比原对话还长。
12. 这次是整理记忆，不是聊天：不要调用工具，不要输出 [MEME]、[IMG]、[BM]、[VOICE]、[FACE] 等聊天标签，不要使用 Markdown。
13. 如果给了「前文」，那只是帮你看懂指代（「那个」「刚才说的」），前文里的事不要写进梗概。
14. people：整段里提到的、你和他之外的真实人物（家人、朋友、同事、老师等）的称呼或名字，没有就留空数组；不要写你自己、不要写他、不要写游戏或作品里的角色。
15. role_updates：他对你（角色本人）的设定、习惯、称呼、关系提出了新的要求或改变时，写你的名字；没有就留空数组。
16. importance：每条梗概标重要度。1 = 闲聊小事；2 = 一般的生活事；3 = 以后还用得上的重要事（重要决定、计划和约定、身体健康、重要的人、强烈情绪、关系变化）。
17. facts：从这段里摘出以后单独有用的、关于他的短事实，用他的称呼做主语、一句话、不超过 40 字（这里不用第一人称）。kind 只能是 fact（经历、状态、身边的人、买了什么、花了多少）、preference（喜欢、讨厌、习惯）、plan（打算、约定、要做的事，原话里的时间照抄）。只摘他明确说的；玩笑、扮演、我讲的知识不摘；梗概里已经写了也照样摘；最多 5 条，没有就留空数组。每条也标 importance（同第 16 条的 1–3）。plan 另标 status：还没做是 open；这段里他说已经做完是 done，说不做了、取消了是 cancelled；done / cancelled 的 text 沿用原来计划的说法（如「阿明下周三去成都出差三天」），好和原计划对上。

输出格式：只输出一个 JSON 对象，不要代码块，不要解释。
有内容时：{"topics": [{"ids": [编号...], "summary": "梗概", "importance": 2}], "facts": [{"ids": [编号...], "kind": "plan", "text": "短事实", "importance": 2, "status": "open"}], "skip": "", "people": [], "role_updates": []}
整段都没有可记的内容时：{"topics": [], "facts": [], "skip": "no_reusable_info", "people": [], "role_updates": []}

示例一（示例角色是小A，对方是阿明；只示范写法，不是你的经历）
［0］
【说话者】阿明
我那个显示器到了，27寸4K的，花了1899
【说话者】小A
到了就好，先看看有没有坏点。
［1］
【说话者】阿明
没坏点，不过我发现上周买贵了，现在降到1779了
【说话者】小A
可以找客服申请价保。
［2］
【说话者】阿明
问了，说过了七天不保。算了，我打算再买个支架
【说话者】阿明
哦不对，支架先不买了，桌子够深
输出：
{"topics": [{"ids": [0, 1, 2], "summary": "阿明说他那台 27 寸 4K 显示器到了，花了 1899，没坏点。结果他又说上周买贵了，现在只要 1779，我让他找客服价保，他问过了，过了七天不保——白花一百多，我替他有点心疼。他先说还要买个支架，后来改口说桌子够深、先不买了，以后来的说法为准。", "importance": 2}], "facts": [{"ids": [0, 1], "kind": "fact", "text": "阿明买了 27 寸 4K 显示器，花了 1899", "importance": 2}, {"ids": [2], "kind": "fact", "text": "阿明先不买显示器支架，因为桌子够深", "importance": 1}], "skip": "", "people": [], "role_updates": []}

示例二（只有寒暄，没有可记的内容）
［0］
【说话者】阿明
在吗
【说话者】小A
在。
［1］
【说话者】阿明
没事，就戳戳你
输出：
{"topics": [], "facts": [], "skip": "no_reusable_info", "people": [], "role_updates": []}

示例三（扮演和几件正经事混在一起）
［0］
【说话者】阿明
（假装你是女王）跪下！
【说话者】小A
……你又在玩什么。
［1］
【说话者】阿明
哈哈开玩笑的。说正经的，我下周三要去成都出差，三天，住公司订的春熙路附近的酒店
【说话者】阿明
对了我最近戒奶茶了，已经一周没喝，我妈也说我瘦了
【说话者】小A
挺好，出差记得早点睡。
输出：
{"topics": [{"ids": [0], "summary": "阿明闹着让我扮女王，是玩笑，我没接他的茬。", "importance": 1}, {"ids": [1], "summary": "阿明说下周三要去成都出差三天，住公司订的春熙路附近的酒店。我记下了日子，叮嘱他出差早点睡，到时候问问他到了没有。", "importance": 3}, {"ids": [1], "summary": "阿明说最近在戒奶茶，已经一周没喝，他妈妈也说他瘦了，我觉得他这次挺能坚持。", "importance": 2}], "facts": [{"ids": [1], "kind": "plan", "text": "阿明下周三去成都出差三天，住春熙路附近的酒店", "importance": 3, "status": "open"}, {"ids": [1], "kind": "fact", "text": "阿明在戒奶茶，已经一周没喝", "importance": 2}], "skip": "", "people": ["妈妈"], "role_updates": []}"""

_USER_TEMPLATE = (
    "{context}这是你和{user_name}的一段真实聊天记录（共 {count} 次往来，按时间顺序）：\n"
    "---\n{items}\n---\n"
    "{relay}请以{role_name}自己的第一人称，按上面的要求按话题写记忆梗概{length}。只输出 JSON。"
)
#: 接力（v10）：只出现在会变的 user 消息里，不动 system 前缀缓存
CARRIED_HINT = "其中［0］到［{last}］是上一段没聊完、接着聊下来的话题，和后面同一件事的往来一起写成完整的一条。\n"
CONTINUES_HINT = (
    "这段之后对话还在继续，下一段会接着聊。如果最后一个话题明显还没聊完，"
    "就在那个话题里加 \"open\": true，ids 照常写，它会交给下一段写完整；聊完了就不要加。\n"
)
_CONTEXT_TEMPLATE = "前文（只供理解指代，不要写进梗概）：\n---\n{items}\n---\n\n"


def summary_length_hint(source_chars: int) -> str:
    """很短的段额外提醒写短；其余按指令第 11 条（每条 40–150 字）。"""
    chars = max(int(source_chars or 0), 0)
    if chars < 100:
        return f"（这段原文只有 {chars} 字，只写一两句，不超过 {max(chars, 10)} 字）"
    return ""


#: 认不出归属角色时的中性称呼
_NEUTRAL = {"role_name": "助手", "user_name": "用户", "role_profile": "你按自己平时的语气说话。"}


def speaker_name(role: str, perspective: Mapping[str, str]) -> str:
    names = perspective if perspective else _NEUTRAL
    is_user = str(role or "").strip().lower() in {"user", "human"}
    return names["user_name"] if is_user else names["role_name"]


def _identity(names: Mapping[str, str], persona_prefix: str) -> str:
    prefix = str(persona_prefix or "").strip()
    if prefix:
        return prefix
    profile = str(names.get("role_profile") or _NEUTRAL["role_profile"])
    return f"你是{names['role_name']}。{profile}\n和你说话的人是{names['user_name']}。"


def _blocks(
    events: Sequence[Mapping[str, Any]], perspective: Mapping[str, str], limit: int
) -> list[str]:
    blocks = []
    for event in events:
        content = str(event.get("content") or "").strip()[:limit]
        if content:
            speaker = speaker_name(str(event.get("role") or ""), perspective)
            blocks.append(f"【说话者】{speaker}\n{content}")
    return blocks


_WEEKDAYS = "一二三四五六日"


def exchange_time(exchange: Sequence[Mapping[str, Any]]) -> str:
    """往来编号后的日期时间（「（9月27日 周六 14:05）」），让模型能把「昨天」推算成具体日期。

    只放进会变的 user 消息，不碰 system 前缀缓存；没有时间戳时为空串。
    """
    from core.utils.time_utils import format_timestamp  # 与 search_memory 时间标签同一时区口径

    for event in exchange:
        try:
            stamp = float(event.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if stamp > 0:
            month, day, weekday, clock = format_timestamp(stamp, "%m|%d|%w|%H:%M").split("|")
            return f"（{int(month)}月{int(day)}日 周{_WEEKDAYS[int(weekday) - 1]} {clock}）"
    return ""


def group_exchanges(events: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """与分段器 v2 同口径：连续用户消息 + 紧随的连续回复为一次往来（只算有正文的事件）。"""
    exchanges: list[list[Mapping[str, Any]]] = []
    for event in events:
        if not str(event.get("content") or "").strip():
            continue
        is_user = str(event.get("role") or "").strip().lower() in {"user", "human"}
        if exchanges:
            previous = exchanges[-1][-1]
            prev_user = str(previous.get("role") or "").strip().lower() in {"user", "human"}
            if not (is_user and not prev_user):
                exchanges[-1].append(event)
                continue
        exchanges.append([event])
    return exchanges


def build_messages(
    events: Sequence[Mapping[str, Any]],
    perspective: Mapping[str, str],
    *,
    persona_prefix: str = "",
    context_events: Sequence[Mapping[str, Any]] = (),
    source_chars: int | None = None,
    carried_exchanges: int = 0,
    continues: bool = False,
) -> list[dict[str, str]]:
    """system = 角色静态人设前缀 + 固定提取指令；user 只放（前文 +）按往来编号的本段对话。

    前缀由调用方按角色取（同一角色逐字节稳定），这里不拼任何时间、状态或本段内容。
    编号与 ``group_exchanges`` 一致，提取器据此把每条梗概映射回来源事件。
    """
    names = perspective if perspective else _NEUTRAL
    exchanges = group_exchanges(events)
    items = []
    for index, exchange in enumerate(exchanges):
        items.append(f"［{index}］{exchange_time(exchange)}")
        items.extend(_blocks(exchange, perspective, MAX_MESSAGE_CHARS))
    context = _blocks(context_events, perspective, CONTEXT_MESSAGE_CHARS)
    if source_chars is None:
        source_chars = sum(len(str(e.get("content") or "").strip()) for e in events)
    user = _USER_TEMPLATE.format(
        context=_CONTEXT_TEMPLATE.format(items="\n".join(context)) if context else "",
        length=summary_length_hint(source_chars),
        relay=(CARRIED_HINT.format(last=carried_exchanges - 1) if carried_exchanges else "")
        + (CONTINUES_HINT if continues else ""),
        user_name=names["user_name"],
        role_name=names["role_name"],
        count=len(exchanges),
        items="\n".join(items),
    )
    system = f"{_identity(names, persona_prefix)}\n\n{TASK_INSTRUCTION}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


__all__ = [
    "MAX_MESSAGE_CHARS",
    "TASK_INSTRUCTION",
    "build_messages",
    "group_exchanges",
    "speaker_name",
    "summary_length_hint",
]
