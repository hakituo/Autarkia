"""验证后端错误详情（错误码 / 上游状态 / 原始错误串）能透传到 Android 端。

背景：App 上所有生成失败都只显示「AI 服务暂时不可用，请稍后重试」，
422 敏感词拦截、timeout、限流在界面上长得一模一样。用户要求
「后端怎么给就怎么显示」，所以这条链路上每一环都要保留原始信息：

provider chunk(details.status/body) -> LLMStreamError.details
    -> error 事件 details.upstream_status/upstream_body
    -> Android StreamEvent.Error(errorCode/detail/httpStatus)
    -> Snackbar 中的 describe()

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_error_detail_propagation.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"

FAILED = []


def check(condition: bool, desc: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {desc}")
    if not condition:
        FAILED.append(desc)


def verify_sensitive_422() -> None:
    from core.agents.chat_agent_components.streaming import (
        _build_upstream_error_event,
        _friendly_upstream_error,
    )
    from core.agents.chat_agent_components.streaming_pipeline import (
        LLMStreamError,
        StreamTagSession,
    )

    print("\n[1/3] 后端：上游 422 敏感输入不再被说成「服务不可用」")
    chunk = {
        "error": "API returned 422",
        "error_code": "non_retryable",
        "non_retryable": True,
        "details": {"status": 422, "body": "input new_sensitive (1026)"},
    }
    session = StreamTagSession(
        agent=None,
        user_id="verify_error_detail",
        is_sensitive_mode=False,
        messages=[],
        model_path="local",
    )
    try:
        asyncio.run(session.process_chunk(chunk))
    except LLMStreamError as exc:
        check(exc.error_code == "non_retryable", f"错误码随异常透传（{exc.error_code}）")
        check(exc.details.get("status") == 422, "上游状态码保留在 LLMStreamError.details")
        check("new_sensitive" in str(exc.details.get("body")), "上游原话保留在 details.body")
        event = _build_upstream_error_event(
            exc,
            error_code=exc.error_code,
            raw=exc.raw,
            upstream_details=exc.details,
        )
    else:
        check(False, "敏感输入 chunk 未被识别为错误")
        return

    check("敏感" in event["message"], f"message 点明是敏感内容被拒（{event['message']}）")
    check(event["details"].get("upstream_status") == 422, "事件 details.upstream_status = 422")
    check(
        "new_sensitive" in str(event["details"].get("upstream_body")),
        "事件 details.upstream_body 保留上游原话",
    )
    check(event["error_code"] == "non_retryable", "事件 error_code 原样保留")

    plain_422 = _friendly_upstream_error("API returned 422", {"status": 422, "body": "bad request"})
    check("422" in plain_422, f"普通 422 也标注 HTTP 422（{plain_422}）")
    check("超时" in _friendly_upstream_error("request timeout"), "timeout 分类不受影响")
    check(
        "繁忙" in _friendly_upstream_error("HTTP 429 too many requests"),
        "限流分类不受影响",
    )


def verify_android_model() -> None:
    print("\n[2/3] Android：错误模型与解析器")

    stream_event = (ANDROID / "data/remote/api/StreamEvent.kt").read_text(encoding="utf-8")
    check("val errorCode: String? = null" in stream_event, "StreamEvent.Error 带 errorCode")
    check("val detail: String? = null" in stream_event, "StreamEvent.Error 带 detail")
    check("val httpStatus: Int? = null" in stream_event, "StreamEvent.Error 带 httpStatus")
    check("fun describe()" in stream_event, "提供统一展示文案 describe()")
    check("errorFromJsonObject(obj)" in stream_event, "SSE type=error 走统一解析")
    check("[$code] $message" not in stream_event, "不再靠拼字符串塞错误码")

    payload = (ANDROID / "data/remote/api/ChatErrorPayload.kt").read_text(encoding="utf-8")
    check("fun errorFromJsonObject" in payload, "统一解析后端错误 JSON")
    check("upstream_status" in payload and "upstream_body" in payload, "详情读取上游状态与原始响应")
    check("is JsonArray" in payload, "FastAPI 422 数组形式的 detail 可解析")
    check("fun errorFromHttpResponse" in payload, "HTTP 非 2xx 交给 errorBody 解析")
    check("SocketTimeoutException" in payload, "超时与网络异常分类明确")


def verify_android_wiring() -> None:
    print("\n[3/3] Android：接线到 UI")

    repo = (ANDROID / "data/repository/ChatRepositoryImpl.kt").read_text(encoding="utf-8")
    check("errorBody()?.string()" in repo, "Repository 读取 errorBody")
    check("errorFromHttpResponse(response.code()" in repo, "非 2xx 带上状态码与后端原因")
    check('errorFromThrowable(e, "读取流失败")' in repo, "读流异常分类")

    streamer = (ANDROID / "presentation/chat/send/AssistantReplyStreamer.kt").read_text(
        encoding="utf-8"
    )
    check("event.describe()" in streamer, "Snackbar 展示后端给的全部信息")
    check('errorFromThrowable(e, "生成失败")' in streamer, "兜底异常也带类型与原始信息")

    observer = (ANDROID / "presentation/chat/ChatSessionObserver.kt").read_text(encoding="utf-8")
    check("errorCode = message.errorCode" in observer, "WebSocket 错误也带上 error_code")


def main() -> int:
    verify_sensitive_422()
    verify_android_model()
    verify_android_wiring()

    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAIL: {len(FAILED)} 项未通过")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("PASS: 后端错误详情可一路透传到 Android 端")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
