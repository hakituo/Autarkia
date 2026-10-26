"""验证聊天页语音输入是「边说边出字、点完成立刻落字」的实时体验。

需求（2026-10-25 设计稿「Aveline Android Controls」）：
1. 录音过程中把 ASR 的流式中间结果实时上屏，输入栏原位显示，不用等说完；
2. 点「完成」时立刻把已经上屏的文本落进输入框，不等收尾解码；
3. 收尾解码 / 模型加载不得占主线程（否则就是"点完停止愣几秒"）；
4. 断句（endpoint）后已识别的内容不能丢，最终结果只替换「完成」时提交的那一段。

对应实现：
- SherpaNcnnAsrEngine：committedText 累积已断句文本，partialText 恒为
  "已确认句 + 当前句"；endpoint 命中时**先累积再 reset**；
  stopListening 不再同步 flush，改为 IO 协程（等录音循环退出后再 inputFinished），
  结果通过 state 发出；
- VoiceInputManager：开录前清空中间态、collector 不泄漏；模型加载与首次开录都挪到后台，
  并提供 isModelLoaded() 供启动路径判断；
- InputArea / ChatVoiceInputPanel：输入栏原位切成语音态（实时文本 + 波形 + 计时 +
  取消/完成），不再另挂转写横幅；
- ChatVoiceInputController：点「完成」先把 voicePartialText 落进输入框，最终结果回来
  只替换这一段；
- ChatVoiceInputController：最终结果落进输入框后清空中间态并 reset 单例。

运行：venv_cpu/Scripts/python.exe tests/scripts/android_frontend/verify_asr_streaming.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
SHERPA_ENGINE = APP_MAIN / "services/SherpaNcnnAsrEngine.kt"
VOICE_MANAGER = APP_MAIN / "services/VoiceInputManager.kt"
CHAT_DIR = APP_MAIN / "presentation/chat"
INPUT_AREA = APP_MAIN / "presentation/components/InputArea.kt"
CHAT_INPUT_BARS = CHAT_DIR / "ChatInputBars.kt"
VOICE_PANEL = CHAT_DIR / "ChatVoiceInputPanel.kt"
CHAT_SCREEN = CHAT_DIR / "ChatScreen.kt"
# 底部区域（含输入栏接线）在 2026-09-24 从 ChatScreen 拆到 ChatBottomArea.kt，检查点跟着搬家
CHAT_BOTTOM_AREA = CHAT_DIR / "ChatBottomArea.kt"
CHAT_VOICE_CONTROLLER = CHAT_DIR / "ChatVoiceInputController.kt"
CHAT_VIEW_MODEL = CHAT_DIR / "ChatViewModel.kt"
VOICE_RELATED_FILES = (
    SHERPA_ENGINE,
    VOICE_MANAGER,
    INPUT_AREA,
    CHAT_INPUT_BARS,
    VOICE_PANEL,
    CHAT_SCREEN,
    CHAT_BOTTOM_AREA,
    CHAT_VOICE_CONTROLLER,
    CHAT_VIEW_MODEL,
)

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
# Kotlin 属性委托（`val x by y`）会隐式调用 getValue/setValue，正文里搜不到名字，不算未使用
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    body = "\n".join(
        line
        for line in lines
        if not line.startswith("import ") and not line.startswith("package ")
    )
    unused: list[str] = []
    for line in lines:
        if not line.startswith("import ") or line.strip() in DELEGATE_IMPORTS:
            continue
        matched = IMPORT_RE.match(line)
        if not matched:
            continue
        fq_name, alias = matched.group(1), matched.group(2)
        if fq_name.endswith("*"):
            continue
        name = alias or fq_name.rsplit(".", 1)[-1]
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            unused.append(line)
    return unused


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("聊天页 ASR 实时输出验证")
    print("=" * 70)

    engine = SHERPA_ENGINE.read_text(encoding="utf-8")
    manager = VOICE_MANAGER.read_text(encoding="utf-8")
    input_area = INPUT_AREA.read_text(encoding="utf-8")
    bars = CHAT_INPUT_BARS.read_text(encoding="utf-8")
    panel = VOICE_PANEL.read_text(encoding="utf-8")
    screen = CHAT_SCREEN.read_text(encoding="utf-8")
    bottom_area = CHAT_BOTTOM_AREA.read_text(encoding="utf-8")
    controller = CHAT_VOICE_CONTROLLER.read_text(encoding="utf-8")
    view_model = CHAT_VIEW_MODEL.read_text(encoding="utf-8")

    # 1. 引擎层：断句累积，流式文本不丢字
    results.append(
        _check(
            "private var committedText" in engine and "fun combineText(" in engine,
            "SherpaNcnnAsrEngine 累积已断句文本并提供 combineText 拼接",
        )
    )
    results.append(
        _check(
            "val combined = combineText(text)" in engine
            and "_partialText.value = combined" in engine,
            "partialText 输出的是「已确认句 + 当前句」的完整流式文本",
        )
    )
    commit_pos = engine.find("committedText = combineText(text)")
    reset_pos = engine.find("recognizer?.reset(recreate = false)", commit_pos)
    results.append(
        _check(
            commit_pos != -1 and reset_pos != -1 and commit_pos < reset_pos,
            "endpoint 命中时先累积当前句、后 reset（顺序反了会丢句）",
        )
    )
    results.append(
        _check(
            engine.count('committedText = ""') >= 3,
            "开始录音 / cancel / reset 都会清空 committedText（3 处）",
        )
    )

    # 2. 收尾解码不能占主线程
    stop_start = engine.find("fun stopListening()")
    stop_body = engine[stop_start : engine.find("fun cancel()", stop_start)]
    results.append(
        _check(
            stop_start != -1
            and "engineScope.launch" in stop_body
            and "inputFinished()" in stop_body,
            "stopListening 把收尾解码放进 IO 协程（不再在主线程 flush）",
        )
    )
    results.append(
        _check(
            "pendingRecord?.join()" in stop_body,
            "收尾解码前先等录音循环退出，避免和 acceptSamples 并发进 native",
        )
    )
    results.append(
        _check(
            "if (_state.value != AsrState.Processing) return@launch" in stop_body,
            "cancel 之后不再把迟到的识别结果抛回 UI",
        )
    )

    # 3. 模型加载 / 开录路径不卡主线程
    results.append(
        _check(
            "scope.launch { sherpaNcnnEngine.initialize() }" in manager,
            "VoiceInputManager 在后台预热 ASR 模型（不是点麦克风时才在主线程加载）",
        )
    )
    results.append(
        _check(
            "sherpaNcnnEngine.isModelLoaded()" in manager
            and manager.count("sherpaStartJob") >= 3,
            "首次开录改成后台加载完再启动，并可在加载期间被 stop/cancel 取消",
        )
    )
    results.append(
        _check(
            manager.count("sherpaObserverJob = scope.launch {") == 1
            and "sherpaNcnnEngine.partialText.collect" in manager,
            "partialText/amplitude 转发协程挂在 sherpaObserverJob 上（不再每次开录新起一组）",
        )
    )

    # 4. UI 层：输入栏原位语音态 + 实时文本
    results.append(
        _check(
            "voicePanel: (@Composable () -> Unit)? = null" in input_area
            and "voicePanel()" in input_area,
            "InputArea 支持用 voicePanel 原位替换输入区（不另挂横幅）",
        )
    )
    results.append(
        _check(
            "fun ChatVoiceInputPanel(" in panel
            and "partialText.isNotBlank()" in panel
            and "VoiceWaveBars(" in panel,
            "ChatVoiceInputPanel 实时展示 ASR 中间文本并带音量波形",
        )
    )
    results.append(
        _check(
            "onCancel = onVoiceCancel" in bars
            and "onFinish = onVoiceFinish" in bars
            and "ChatVoiceInputPanel(" in bars,
            "ChatBottomBar 录音时切到语音面板，取消/完成各自接线",
        )
    )
    results.append(
        _check(
            "ChatVoiceTranscribingBar" not in bottom_area
            and "ChatVoiceTranscribingBar" not in bars,
            "旧的转写横幅已移除，不再有「录音中 + 收尾识别」两套提示",
        )
    )
    results.append(
        _check(
            "voicePartialText = uiState.voicePartialText" in bottom_area
            and "voiceAmplitude = uiState.voiceAmplitude" in bottom_area
            and "ChatBottomArea(" in screen,
            "聊天页把 voicePartialText / voiceAmplitude 接到输入栏（实时上屏）",
        )
    )
    results.append(
        _check(
            "onVoiceFinish = { viewModel.stopVoiceRecording() }" in screen
            and "onVoiceCancel = { viewModel.cancelVoiceRecording() }" in screen,
            "面板「完成」= 停止录音，「取消」= 丢弃本轮",
        )
    )

    # 5. 「完成」立刻落字，最终结果只替换提交过的那一段
    results.append(
        _check(
            "val partial = current.voicePartialText.trim()" in controller
            and "appendVoiceText(it.inputText, partial)" in controller,
            "stopRecording 先把已实时上屏的文本落进输入框，再停引擎",
        )
    )
    results.append(
        _check(
            "replaceCommittedText(it.inputText, committed, state.text)" in controller,
            "最终结果只替换「完成」时提交的那一段（不覆盖用户随后补的字）",
        )
    )
    results.append(
        _check(
            "voicePartialText = \"\"" in controller
            and "voiceInputManager.reset()" in controller,
            "Result 消费后清空中间态并重置单例（防止旧识别文本重放回输入框）",
        )
    )
    results.append(
        _check(
            "sherpaNcnnEngine.reset()" in manager,
            "VoiceInputManager.reset() 连 sherpa 引擎状态一起重置",
        )
    )
    results.append(
        _check(
            "voiceInputController.cancelRecording()" in view_model,
            "ChatViewModel.onCleared 用 cancelRecording 丢弃未消费的识别结果",
        )
    )

    # 6. 没有留下未使用 import
    unused: list[str] = []
    for path in VOICE_RELATED_FILES:
        for line in find_unused_imports(path):
            unused.append(f"{path.name}: {line}")
    results.append(
        _check(
            not unused,
            "相关文件无未使用 import"
            + ("" if not unused else "，实际：\n    " + "\n    ".join(unused)),
        )
    )

    print("\n" + "-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：边说边出字，点完成立刻落字，收尾解码不再卡主线程。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
