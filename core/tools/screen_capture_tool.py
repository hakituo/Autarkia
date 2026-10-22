"""
屏幕截图分析工具 - 截图用户正在看的窗口并用视觉模型分析

设计要点：
- 仅 Master 可调用（隐私保护，参考 QQ /截图 命令的权限模型）
- 类 Steam 挂机检测：系统空闲超过阈值（默认 5 分钟）则告知 AI "电脑在挂机"，不截图
- 多屏 + 高 DPI 兼容：坐标与位图统一走物理像素（见 screen_capture/win_screen.py），
  优先截鼠标所在窗口（拿不到则退前台窗口），再退它所在的整块显示器
- 复用全局 VisionModule（Qwen3-VL 云端）进行图像分析
- 截图保留到 companion_data/temp/screen_captures/，自动清理超过 24 小时的旧文件

调用场景：
- 用户询问 "我在干嘛" / "我屏幕上是什么"
- 主动关怀时确认用户当前活动状态
"""

import asyncio
import os
import time
from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.tools.screen_capture import win_screen
from core.utils.logger import get_logger

logger = get_logger("screen_capture_tool")

# ── 配置常量 ─────────────────────────────────────────────
_COOLDOWN_SECONDS = 30.0  # 调用冷却，避免 AI 频繁截图浪费视觉模型 token
_IDLE_THRESHOLD_SECONDS = 300.0  # 5 分钟无键鼠操作算挂机
_SCREENSHOT_TTL_SECONDS = 24 * 3600  # 截图保留 24 小时
_MAX_SCREENSHOTS = 50  # 目录最多保留 50 张截图
# 窗口占满显示器到这个比例就按整屏截（最大化窗口取整屏更完整，也省得漏边）
_FULLSCREEN_RATIO = 0.92
# 小于这个边长的窗口不值得截，按显示器处理
_MIN_WINDOW_SIDE = 64

# 截图保存目录（companion_data 已在 .gitignore）
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCREENSHOT_DIR = os.path.join(
    _PROJECT_ROOT, "companion_data", "temp", "screen_captures"
)

# 模块级冷却状态（进程内）
_last_capture_ts = 0.0


class ScreenCaptureInput(BaseModel):
    question: Optional[str] = Field(
        default=None,
        description=(
            "想了解屏幕上的什么内容，例如「用户在玩什么游戏」"
            "「用户在看什么视频」「用户在写什么代码」。"
            "不填则默认分析「用户当前在做什么」。"
        ),
    )


class ScreenCaptureTool(BaseTool):
    """截图用户正在看的窗口并用视觉模型分析，了解用户正在做什么。"""

    name = "look_at_screen"
    description = (
        "截图当前电脑屏幕并用视觉模型分析，了解用户正在做什么。"
        "会先检测系统是否处于挂机状态（无键鼠操作超过 5 分钟），"
        "若挂机则直接返回挂机信息不截图；否则截取鼠标所在窗口（鼠标下无有效窗口"
        "时退到前台窗口，再退其所在显示器）并分析。"
        "仅 Master 可用，调用有 30 秒冷却。"
        "可在用户询问「我在干嘛」或主动关怀时调用。"
    )
    short_description = "截图并分析用户屏幕（仅 Master）"
    category = "utility"
    args_schema = ScreenCaptureInput

    async def _run(self, question: Optional[str] = None) -> str:
        # 1. Master 权限检查
        if not self._is_master():
            return "权限不足：屏幕截图工具仅 Master 可用"

        # 2. 冷却检查（进程内）
        global _last_capture_ts
        now = time.time()
        left = _COOLDOWN_SECONDS - (now - _last_capture_ts)
        if left > 0:
            return f"截图冷却中，请 {left:.0f} 秒后再试"

        # 3. 挂机检测（同步 API 放线程池）
        try:
            idle_seconds = await asyncio.to_thread(self._get_idle_seconds)
        except Exception as e:
            logger.warning("获取系统空闲时间失败，按非挂机处理: %s", e)
            idle_seconds = 0.0

        if idle_seconds >= _IDLE_THRESHOLD_SECONDS:
            _last_capture_ts = now
            mins = int(idle_seconds // 60)
            return (
                f"电脑处于挂机状态（已 {mins} 分钟无键鼠操作），未截图。"
                "用户可能离开了电脑或在挂机看视频/挂游戏。"
            )

        # 4. 截图（PIL ImageGrab 是同步阻塞，放线程池）
        try:
            image_path = await asyncio.to_thread(self._capture_active_screen)
        except Exception as e:
            logger.error("截图失败: %s", e, exc_info=True)
            return f"截图失败: {e}"

        _last_capture_ts = now

        # 5. 调用视觉模型分析
        q = (question or "").strip()
        if q:
            prompt = (
                f"这是一张用户电脑屏幕的截图。请回答：{q}"
                "请基于截图内容给出具体、准确的回答，"
                "如果截图中有应用名称、网页标题、游戏画面等关键信息请一并说明。"
            )
        else:
            prompt = (
                "这是一张用户电脑屏幕的截图。请描述用户当前在做什么，"
                "重点说明：(1) 用户在使用什么应用/游戏/网页；"
                "(2) 具体内容是什么（如游戏名、视频标题、代码项目等）；"
                "(3) 用户的活动状态（正在操作/播放中/加载中等）。"
                "请简洁准确地回答，不要遗漏关键信息。"
            )

        try:
            from core.core_engine.service_singletons import get_vision_module

            vm = get_vision_module()
            if vm is None:
                return (
                    f"截图成功但视觉模块未初始化，无法分析。截图路径: {image_path}"
                )
            result = await vm.describe_image(image_path, prompt)
            if isinstance(result, dict):
                if result.get("status") == "success":
                    desc = (
                        result.get("response")
                        or result.get("description")
                        or ""
                    )
                    if desc:
                        return f"屏幕内容分析：{desc}"
                    return "视觉分析完成但未返回内容"
                return (
                    f"视觉分析失败: {result.get('error', '未知错误')}"
                    f"（截图已保存: {image_path}）"
                )
            return str(result)
        except Exception as e:
            logger.error("视觉分析失败: %s", e, exc_info=True)
            return (
                f"截图成功但视觉分析失败: {e}。截图路径: {image_path}"
            )

    # ── 挂机检测 / 屏幕坐标（委托给 win_screen）────────────
    @staticmethod
    def _get_idle_seconds() -> float:
        """获取系统全局空闲时间（秒）。非 Windows 返回 0.0（视为非挂机）。"""
        return win_screen.get_idle_seconds()

    @staticmethod
    def _get_active_screen_bbox() -> Optional[tuple]:
        """获取当前活动窗口（或鼠标）所在屏幕的边界 (left, top, right, bottom)。

        返回 None 时调用方回退到整屏截图。
        """
        return win_screen.get_active_monitor_rect()

    # ── 截图实现 ─────────────────────────────────────────
    def _capture_active_screen(self) -> str:
        """截取鼠标所在窗口（不可用时回退前台窗口 / 显示器），返回文件路径。

        坐标与位图必须同一坐标系（见 screen_capture/win_screen.py 的说明），
        否则 4K + 150% 缩放下只会截到屏幕左上角 2/3 × 2/3 那一块。

        截图后按原图分辨率自适应压缩为 JPEG（保留文字细节，控制体积）。
        """
        os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
        self._cleanup_old_screenshots()

        bbox, target = self._resolve_capture_bbox()
        image = win_screen.grab_region(bbox)

        src_w, src_h = image.size
        compressed_bytes, target_w = self._compress_screenshot(image)
        dst_size_kb = len(compressed_bytes) / 1024

        file_name = (
            f"screen_{time.strftime('%Y%m%d_%H%M%S')}"
            f"_{int(time.time() * 1000) % 1000:03d}.jpg"
        )
        file_path = os.path.join(_SCREENSHOT_DIR, file_name)
        with open(file_path, "wb") as f:
            f.write(compressed_bytes)

        scale_pct = (target_w / src_w * 100) if src_w > 0 else 100
        logger.info(
            "截图保存到: %s (%s, bbox=%s, 原始 %dx%d → %d宽 %.0f%%, JPEG %dKB)",
            file_path, target, bbox, src_w, src_h, target_w, scale_pct,
            int(dst_size_kb),
        )
        return file_path

    def _resolve_capture_bbox(self) -> tuple[Optional[tuple], str]:
        """决定这次截哪一块，返回 (bbox, 说明)。

        优先级：鼠标所在窗口 → 前台窗口 → 它们所在的整块显示器 → 整屏。
        窗口已最大化（几乎占满显示器）或过小时按整屏截，省得漏掉任务栏和边缘。
        bbox 是绝对物理像素坐标，None 表示整屏。
        """
        monitor_rect = win_screen.get_active_monitor_rect()
        candidates = (
            (win_screen.get_window_under_cursor_rect(), "鼠标所在窗口"),
            (win_screen.get_foreground_window_rect(), "前台窗口"),
        )
        for window_rect, label in candidates:
            if not window_rect:
                continue
            if monitor_rect is None:
                return window_rect, label
            rect = _intersect_rect(window_rect, monitor_rect)
            if rect is None:
                continue
            if min(rect[2] - rect[0], rect[3] - rect[1]) < _MIN_WINDOW_SIDE:
                continue
            monitor_area = _area(monitor_rect)
            if monitor_area and _area(rect) >= monitor_area * _FULLSCREEN_RATIO:
                return monitor_rect, "显示器（窗口已最大化）"
            return rect, label
        if monitor_rect:
            return monitor_rect, "显示器"
        return None, "整屏"

    def _compress_screenshot(self, image) -> tuple[bytes, int]:
        """按原图分辨率自适应压缩截图，返回 (JPEG bytes, 目标宽度)。

        分档策略（基于 Qwen3-VL 实测 + 官方 2048px 警戒线）：
        - 原 ≤1920：不缩放（1080p 本就在理想区间）
        - 原 1921-2560（2.5K）：缩到 1920（75%，实测文字零损失）
        - 原 2561-3840（4K）：缩到 2560（67%，避免粗暴砍半丢细节）
        - 原 >3840（5K+）：缩到 3000（兜底，避免过度缩放）

        统一 JPEG q=85：实测与 PNG 识别效果一致，体积省 40%+。
        """
        from io import BytesIO
        from PIL import Image

        src_w, src_h = image.size
        target_w = self._get_compress_target_width(src_w)

        if src_w > target_w:
            new_h = int(src_h * target_w / src_w)
            image = image.resize((target_w, new_h), resample=Image.LANCZOS)

        if image.mode == "RGBA":
            image = image.convert("RGB")

        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue(), target_w

    @staticmethod
    def _get_compress_target_width(src_width: int) -> int:
        """根据原图宽度返回压缩目标宽度。"""
        if src_width <= 1920:
            return src_width
        if src_width <= 2560:
            return 1920
        if src_width <= 3840:
            return 2560
        return 3000

    # ── 截图清理 ─────────────────────────────────────────
    def _cleanup_old_screenshots(self) -> None:
        """清理超过 TTL 的旧截图，并限制目录最大文件数。"""
        try:
            if not os.path.isdir(_SCREENSHOT_DIR):
                return
            now = time.time()
            kept: list[tuple[float, str]] = []
            for name in os.listdir(_SCREENSHOT_DIR):
                path = os.path.join(_SCREENSHOT_DIR, name)
                if not os.path.isfile(path):
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if now - mtime > _SCREENSHOT_TTL_SECONDS:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                else:
                    kept.append((mtime, path))
            # 限制最大数量：保留最新的 _MAX_SCREENSHOTS 个
            if len(kept) > _MAX_SCREENSHOTS:
                kept.sort()
                excess = len(kept) - _MAX_SCREENSHOTS
                for _, path in kept[:excess]:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        except Exception as e:
            logger.debug("清理旧截图失败: %s", e)


# ── 模块级小工具 ─────────────────────────────────────────
def _intersect_rect(a: tuple, b: tuple) -> Optional[tuple]:
    """两个矩形的交集；不相交返回 None。"""
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _area(rect: tuple) -> int:
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
