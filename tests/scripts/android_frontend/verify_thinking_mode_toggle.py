"""验证「思考模式」开关从模型页一路接到 LLM payload 的完整链路。

需求（2026-10-28）：安卓「模型」页（伴侣详情第 3 个 Tab）要有思考模式开关，
按角色保存；发消息时随请求体带 thinking；后端据此给 DeepSeek / MiniMax / 智谱
的 payload 写 ``thinking`` 字段，不支持的 provider 忽略。没设置过时不传该字段，
继续沿用后端配置。

链路（任一环断掉开关就是摆设）：
    CompanionModelTab（AvelineSwitch）
      → CompanionScreen / ChatCompanionPanel
      → ChatViewModel.setThinkingForCurrentRole
      → RoleModelController（RoleScopedPreferences 按角色持久化）
      → ChatSendController → AssistantReplyStreamer（冻结本轮）
      → ChatRepository.sendMessageStreaming(thinking=)
      → ChatRepositoryImpl → MessageRequest.thinking
      → routers/v1/chat.py 读 body.thinking → normalize_thinking
      → ContextVar → streaming.py / handler_llm_loop.py 注入 thinking_enabled
      → DeepSeekClient._build_payload 写 payload["thinking"]

运行：venv_cpu/bin/python tests/scripts/android_frontend/verify_thinking_mode_toggle.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "core/agents/chat_agent_components"
JAVA = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"

THINKING_MODE = CORE / "thinking_mode.py"
CHAT_ROUTER = ROOT / "routers/v1/chat.py"
STREAMING = CORE / "streaming.py"
LLM_LOOP = CORE / "handler_llm_loop.py"

MESSAGE_REQUEST = JAVA / "data/remote/dto/MessageRequest.kt"
CHAT_REPOSITORY = JAVA / "domain/repository/ChatRepository.kt"
CHAT_REPOSITORY_IMPL = JAVA / "data/repository/ChatRepositoryImpl.kt"
REPLY_STREAMER = JAVA / "presentation/chat/send/AssistantReplyStreamer.kt"
SEND_CONTROLLER = JAVA / "presentation/chat/ChatSendController.kt"
ROLE_MODEL_CONTROLLER = JAVA / "presentation/chat/RoleModelController.kt"
CHAT_VIEW_MODEL = JAVA / "presentation/chat/ChatViewModel.kt"
ROLE_PREFS = JAVA / "data/local/preferences/RoleScopedPreferences.kt"
MODEL_TAB = JAVA / "presentation/companion/CompanionModelTab.kt"
COMPANION_SCREEN = JAVA / "presentation/companion/CompanionScreen.kt"
COMPANION_PANEL = JAVA / "presentation/chat/ChatCompanionPanel.kt"


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("思考模式开关链路验证")
    print("=" * 70)

    thinking_mode = _read(THINKING_MODE)
    router = _read(CHAT_ROUTER)
    streaming = _read(STREAMING)
    llm_loop = _read(LLM_LOOP)

    # 1. 后端：请求解析 + 请求级 ContextVar
    results.append(
        _check(
            all(
                name in thinking_mode
                for name in (
                    "def normalize_thinking(",
                    "def set_request_thinking(",
                    "def reset_request_thinking(",
                    "def get_request_thinking(",
                )
            ),
            "thinking_mode 提供 normalize + 请求级 ContextVar 读写",
        )
    )
    results.append(
        _check(
            "normalize_thinking(" in router and 'message.get("thinking"' in router,
            "chat 路由从请求体读 thinking / enable_thinking 并归一",
        )
    )
    results.append(
        _check(
            router.count("set_request_thinking(thinking_flag)") == 2
            and router.count("reset_request_thinking(") == 2,
            "流式与非流式各自设置并复原思考开关（不串到后续请求）",
        )
    )

    # 2. 后端：两条生成链路都把开关变成 llm kwargs
    results.append(
        _check(
            'llm_kwargs["thinking_enabled"] = thinking_enabled' in streaming
            and "get_request_thinking()" in streaming,
            "流式链路把思考开关注入 llm_kwargs",
        )
    )
    results.append(
        _check(
            'llm_chat_kwargs["thinking_enabled"] = thinking_enabled' in llm_loop
            and "get_request_thinking()" in llm_loop,
            "非流式生成循环把思考开关注入 llm kwargs",
        )
    )
    results.append(
        _check(
            streaming.count("if thinking_enabled is not None:") == 1
            and llm_loop.count("if thinking_enabled is not None:") == 1,
            "没表态（None）时不传该参数，继续用后端配置",
        )
    )

    # 3. 客户端：DTO / 仓库透传
    message_request = _read(MESSAGE_REQUEST)
    repository = _read(CHAT_REPOSITORY)
    repository_impl = _read(CHAT_REPOSITORY_IMPL)

    results.append(
        _check(
            "val thinking: Boolean? = null" in message_request,
            "MessageRequest 带 thinking 字段（null 表示跟随后端）",
        )
    )
    results.append(
        _check(
            "thinking: Boolean? = null" in repository and "thinking: Boolean?" in repository_impl,
            "ChatRepository 接口与实现都接收 thinking",
        )
    )
    results.append(
        _check(
            repository_impl.count("thinking = thinking") == 2,
            "流式与回退两条请求构造点都透传 thinking",
        )
    )

    # 4. 客户端：发送链路冻结本轮开关
    reply_streamer = _read(REPLY_STREAMER)
    send_controller = _read(SEND_CONTROLLER)
    results.append(
        _check(
            "resolveRoleThinking" in reply_streamer
            and "thinking = resolveRoleThinking()" in reply_streamer,
            "AssistantReplyStreamer 在开轮时冻结思考开关",
        )
    )
    results.append(
        _check(
            "thinking = thinking" in reply_streamer and "resolveRoleThinking = resolveRoleThinking" in send_controller,
            "ChatSendController 把开关从 ViewModel 传到流式生成器",
        )
    )

    # 5. 客户端：按角色持久化 + ViewModel 暴露
    role_prefs = _read(ROLE_PREFS)
    role_model_controller = _read(ROLE_MODEL_CONTROLLER)
    view_model = _read(CHAT_VIEW_MODEL)

    results.append(
        _check(
            "fun getThinking(" in role_prefs
            and "fun setThinking(" in role_prefs
            and 'thinking:${roleDigest' in role_prefs,
            "思考开关按角色（role digest）持久化，未设置返回 null",
        )
    )
    results.append(
        _check(
            "fun requestThinking(" in role_model_controller
            and "fun setThinkingForCurrentRole(" in role_model_controller,
            "RoleModelController 读写当前角色的思考开关",
        )
    )
    results.append(
        _check(
            "resolveRoleThinking = { roleModelController.requestThinking() }" in view_model
            and "fun setThinkingForCurrentRole(" in view_model,
            "ChatViewModel 接入读取与保存入口",
        )
    )

    # 6. UI：模型页开关 + 一路接线
    model_tab = _read(MODEL_TAB)
    companion_screen = _read(COMPANION_SCREEN)
    companion_panel = _read(COMPANION_PANEL)

    results.append(
        _check(
            "AvelineSwitch(" in model_tab and "思考模式" in model_tab,
            "模型页用 AvelineSwitch 渲染思考模式开关",
        )
    )
    results.append(
        _check(
            "thinkingEnabled: Boolean? = null" in model_tab
            and "checked = thinkingEnabled ?: true" in model_tab
            and "onCheckedChange = onThinkingChange" in model_tab,
            "开关状态（未设置按开显示）与回调接到模型页参数",
        )
    )
    results.append(
        _check(
            "thinkingEnabled = thinkingEnabled" in companion_screen
            and "onThinkingChange = onThinkingChange" in companion_screen,
            "CompanionScreen 把思考开关透传给模型 Tab",
        )
    )
    results.append(
        _check(
            "chatViewModel.roleThinking" in companion_panel
            and "onThinkingChange = chatViewModel::setThinkingForCurrentRole" in companion_panel,
            "伴侣详情面板从 ChatViewModel 取状态并接保存回调",
        )
    )

    print("-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：模型页开关 → 请求体 → LLM payload 链路完整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
