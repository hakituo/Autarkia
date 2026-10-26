"""按段梗概提取的提示词（v5：角色静态人设前缀 + 提取指令 + 本段对话）。

v4 的全局固定前缀（角色名、人设自述都放在末尾 user）只能让所有角色共用一小段缓存。
v5 改为**和主对话同一套角色静态人设前缀**：前缀由 ``build_offline_role_prefix`` 离线取出，
同一角色逐字节固定，提取指令固定接在它后面，只有最后一条 user 消息随本段变化。这样：
- 口吻直接继承角色人设，不需要在提示词里再描述一遍性格；
- DeepSeek 按角色分 key 后，每个角色的前缀缓存独立且稳定命中。

写法沿用 v4 的人设回想口吻（第一人称、他说了什么、我当时怎么想怎么应），只把身份来源
从提示词里的自述换成了真实人设前缀。改这里任何字都会让缓存失效，并须升提取器版本。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: 单条消息进提示词的上限（与 C8 实验一致），超长粘贴不撑爆输入
MAX_MESSAGE_CHARS = 1500

TASK_INSTRUCTION = """（下面是整理任务的要求，不是聊天内容，也不是让你继续对话。）

你要把紧接着给你的这段真实聊天记录，整理成你自己的一条记忆。不是回复对方，而是事后回想。
对话里标着【说话者】对方称呼的是对方说的话，标着【说话者】你名字的是你自己说过的话。

写法规则：
1. 梗概用第一人称「我」来写，像自己事后回想那一段：他说了什么、我当时怎么想、怎么应的、哪句话或哪个细节留下来了。要有自己的语气，按你上面的人设和说话方式写，不要冷冰冰的事件摘要，也不要「用户」「助手」这种旁观者称呼。
2. 只写这一段里真的出现的内容：只有他说的一句，就写那一句给我的反应，不要编我回过什么。
3. 事实必须准：人名、称呼、数字、金额、日期时间、地点、物品、原话都不能改。他后来改口的，两个说法都写，以后来的为准。
4. 他说的关于自己的事（经历、计划、喜好、作息、身边的人、买了什么、花了多少钱、做了什么决定）要写全；我讲的知识和科普一句带过，不复述细节。
5. 扮演、玩笑、括号里的指令或临时编的剧情，要写明是扮演或玩笑，不当成真事。
6. 不要动作旁白或括号表演，不要为了显得有文采去堆比喻。
7. 一般 100 到 250 字；他自己的事很多时可以更长。
8. 整段只有寒暄、表情、测试消息、单纯催促，没有任何可记的内容时，输出 skip。
9. 这次是整理记忆，不是聊天：不要调用工具，不要输出 [MEME]、[IMG]、[BM]、[VOICE]、[FACE] 等聊天标签，不要使用 Markdown。

输出格式：只输出一个 JSON 对象，不要代码块，不要解释。
有内容时：{"summary": "梗概正文", "skip": ""}
没内容时：{"summary": "", "skip": "no_reusable_info"}

示例一（示例角色是小A，对方是阿明；只示范写法，不是你的经历）
【说话者】阿明
我那个显示器到了，27寸4K的，花了1899
【说话者】小A
到了就好，先看看有没有坏点。
【说话者】阿明
没坏点，不过我发现上周买贵了，现在降到1779了
【说话者】小A
可以找客服申请价保。
【说话者】阿明
问了，说过了七天不保。算了，我打算再买个支架
【说话者】阿明
哦不对，支架先不买了，桌子够深
输出：
{"summary": "阿明说他那台 27 寸 4K 显示器到了，花了 1899，没坏点。我本来松了口气，结果他又说上周买贵了，现在只要 1779，我让他去找客服价保，他问过了，过了七天不保——白花一百多，我嘴上没说，其实替他有点心疼。他先说还要再买个支架，后来又改口说桌子够深、支架先不买了，以后来的说法为准。", "skip": ""}

示例二（只有寒暄，没有可记的内容）
【说话者】阿明
在吗
【说话者】小A
在。
【说话者】阿明
没事，就戳戳你
输出：
{"summary": "", "skip": "no_reusable_info"}

示例三（扮演和正经事混在一起）
【说话者】阿明
（假装你是女王）跪下！
【说话者】小A
……你又在玩什么。
【说话者】阿明
哈哈开玩笑的。说正经的，我下周三要去成都出差，三天，住公司订的春熙路附近的酒店
【说话者】阿明
对了我最近戒奶茶了，已经一周没喝
输出：
{"summary": "阿明先闹着让我扮女王，是玩笑，我没接他的茬。然后他正经说下周三要去成都出差三天，住公司订的春熙路附近的酒店——我心里记下了日子，到时候问问他到了没有。他还说最近在戒奶茶，已经一周没喝，我觉得他这次挺能坚持。", "skip": ""}"""

_USER_TEMPLATE = (
    "这是你和{user_name}的一段真实聊天记录（共 {count} 条，按时间顺序）：\n"
    "---\n{items}\n---\n"
    "请以{role_name}自己的第一人称，按上面的要求写一条记忆梗概。只输出 JSON。"
)

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


def build_messages(
    events: Sequence[Mapping[str, Any]],
    perspective: Mapping[str, str],
    *,
    persona_prefix: str = "",
) -> list[dict[str, str]]:
    """system = 角色静态人设前缀 + 固定提取指令；user 只放本段对话。

    前缀由调用方按角色取（同一角色逐字节稳定），这里不拼任何时间、状态或本段内容。
    """
    names = perspective if perspective else _NEUTRAL
    blocks = []
    for event in events:
        content = str(event.get("content") or "").strip()[:MAX_MESSAGE_CHARS]
        if content:
            speaker = speaker_name(str(event.get("role") or ""), perspective)
            blocks.append(f"【说话者】{speaker}\n{content}")
    user = _USER_TEMPLATE.format(
        user_name=names["user_name"],
        role_name=names["role_name"],
        count=len(blocks),
        items="\n".join(blocks),
    )
    system = f"{_identity(names, persona_prefix)}\n\n{TASK_INSTRUCTION}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


__all__ = ["MAX_MESSAGE_CHARS", "TASK_INSTRUCTION", "build_messages", "speaker_name"]
