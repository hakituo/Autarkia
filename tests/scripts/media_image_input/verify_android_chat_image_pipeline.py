from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID_CHAT = ROOT / "clients" / "frontend" / "aveline-android" / "android" / "app" / "src" / "main" / "java" / "com" / "aveline" / "ai" / "mobile" / "presentation" / "chat"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"缺少 {label}: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"不应存在 {label}: {needle}")


def main() -> None:
    upload_helper = (ANDROID_CHAT / "ChatUploadHelper.kt").read_text(encoding="utf-8")
    image_text = (ANDROID_CHAT / "ImageMessageText.kt").read_text(encoding="utf-8")
    media_text = (ANDROID_CHAT / "MediaSendText.kt").read_text(encoding="utf-8")
    dynamic_context = (
        ROOT
        / "core"
        / "agents"
        / "chat_agent_components"
        / "streaming_pipeline"
        / "dynamic_context.py"
    ).read_text(encoding="utf-8")
    vision_router = (
        ROOT / "core" / "llm" / "openai_compat" / "vision_router.py"
    ).read_text(encoding="utf-8")

    # 图片/文档统一走 sendAttachments -> MediaSendText.buildAttachments，
    # 图片标记仍由 ImageMessageText 组装。
    require(upload_helper, "sendAttachments(", "Android 图片/附件发送")
    forbid(upload_helper, "describeVision(", "Android 发送前视觉识别")
    require(media_text, "ImageMessageText.buildAttachment", "Android 图片附件标记组装")
    require(image_text, "[图片: ${imageUrl.trim()}]", "图片附件标记")

    # 图片与文档共用同一套附件标记解析（core/image/chat_attachment_input.py）；
    # 多图消息里每张图都会各自升级成 image_url。
    require(dynamic_context, "split_chat_attachment_message", "附件标记解析")
    require(dynamic_context, '"type": "image_url"', "标准多模态 image_url 注入")
    require(dynamic_context, "load_uploaded_image_data_url", "后端本地图片编码")

    require(vision_router, "if is_vision_model(model_name):", "多模态主模型直通判断")
    require(vision_router, "describe_images_via_vl", "纯文本主模型 VL 中转")

    print("[PASS] Android 图片发送已接入统一多模态路由：多模态主模型直看原图，纯文本模型走 VL")


if __name__ == "__main__":
    main()
