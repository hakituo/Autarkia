"""电脑屏幕截图的 Windows 侧原语（只跟 Win32 / Pillow 打交道）

对外只有两类函数：「问坐标」和「按坐标抓图」。业务判断（截哪块、压缩到多大、
存哪里）都在 `core/tools/screen_capture_tool.py`，本模块不含策略。

## 为什么需要单独一层

截图线程默认是 **DPI-unaware**，Win32 返回的坐标被系统按缩放比虚拟化了：
4K 屏 + 150% 缩放时，`GetSystemMetrics` / `GetMonitorInfoW` 只报 2560x1440，
而 Pillow 的 `ImageGrab` 抓出来的是**物理像素**位图 3840x2160。
两个坐标系不一致时，拿 2560x1440 的 bbox 去裁剪 3840x2160 的位图，等于只截到
屏幕左上角 (2560/3840) x (1440/2160) ≈ 67% x 67% 那一块，其余被 PIL 用黑色补齐
（2026-10-02 的截图就是这么来的：1920x1080 里只有左上角有内容，其余全黑）。

这里把「本线程临时切到 per-monitor DPI aware」封装成上下文管理器，保证
「算坐标」和「抓位图」永远落在同一个坐标系（物理像素）里。
"""

from __future__ import annotations

import contextlib
import ctypes
import os
from ctypes import wintypes
from typing import Iterator, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("screen_capture_win")

# 矩形统一用 (left, top, right, bottom)，绝对物理像素
Rect = Tuple[int, int, int, int]

_IS_WINDOWS = os.name == "nt"

# ── Win32 常量 ───────────────────────────────────────────
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_MONITOR_DEFAULTTONEAREST = 0x00000002
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_GA_ROOT = 2
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2（Win10 1703+）
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
# 最小可接受的裁剪边长，低于它认为坐标不可信
_MIN_REGION_SIDE = 8

# 这些类名的窗口是桌面 / 任务栏本身，不算「用户在用的窗口」
_SHELL_WINDOW_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd"})


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


@contextlib.contextmanager
def per_monitor_dpi_aware() -> Iterator[None]:
    """本线程临时切到 per-monitor DPI aware，退出时还原成原来的上下文。

    非 Windows 或系统不支持时直接透传。嵌套调用是安全的：每层都还原到自己
    进来之前的值。
    """
    if not _IS_WINDOWS:
        yield
        return
    try:
        user32 = ctypes.windll.user32
        set_ctx = user32.SetThreadDpiAwarenessContext
    except (AttributeError, OSError):
        yield
        return
    set_ctx.restype = ctypes.c_void_p
    set_ctx.argtypes = [ctypes.c_void_p]
    prev = set_ctx(ctypes.c_void_p(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    try:
        yield
    finally:
        if prev:
            set_ctx(ctypes.c_void_p(prev))


def get_idle_seconds() -> float:
    """系统全局空闲秒数（自上次键鼠输入以来）。

    用 Win32 GetLastInputInfo + GetTickCount，全局空闲不分屏幕。
    非 Windows 或调用失败返回 0.0（视为非挂机）。
    """
    if not _IS_WINDOWS:
        return 0.0
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        lii = _LastInputInfo()
        lii.cbSize = ctypes.sizeof(_LastInputInfo)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        # 注意：GetTickCount 49.7 天后会回绕，此处用差值规避
        millis = (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
        return millis / 1000.0
    except Exception as e:
        logger.warning("获取系统空闲时间失败: %s", e)
        return 0.0


def get_active_monitor_rect() -> Optional[Rect]:
    """当前活动窗口（或鼠标）所在显示器的边界，物理像素。

    前台窗口中心点所在显示器优先，回退鼠标所在显示器，都拿不到返回 None。
    """
    if not _IS_WINDOWS:
        return None
    try:
        with per_monitor_dpi_aware():
            user32 = ctypes.windll.user32
            monitor = 0
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                rect = _get_window_frame_rect(hwnd)
                if rect:
                    point = wintypes.POINT(
                        (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                    )
                    monitor = user32.MonitorFromPoint(
                        point, _MONITOR_DEFAULTTONEAREST
                    )
            if not monitor:
                cursor = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(cursor)):
                    monitor = user32.MonitorFromPoint(
                        cursor, _MONITOR_DEFAULTTONEAREST
                    )
            return _monitor_rect(monitor) if monitor else None
    except Exception as e:
        logger.warning("获取活动屏幕边界失败: %s", e)
        return None


def get_foreground_window_rect() -> Optional[Rect]:
    """前台窗口的可见边界，物理像素；桌面 / 任务栏 / 最小化窗口返回 None。"""
    if not _IS_WINDOWS:
        return None
    try:
        with per_monitor_dpi_aware():
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd or user32.IsIconic(hwnd):
                return None
            if hwnd in (user32.GetShellWindow(), user32.GetDesktopWindow()):
                return None
            if _window_class_name(hwnd) in _SHELL_WINDOW_CLASSES:
                return None
            return _get_window_frame_rect(hwnd)
    except Exception as e:
        logger.warning("获取前台窗口边界失败: %s", e)
        return None


def get_window_under_cursor_rect() -> Optional[Rect]:
    """鼠标指针下那个顶层窗口的可见边界，物理像素；桌面 / 任务栏返回 None。"""
    if not _IS_WINDOWS:
        return None
    try:
        with per_monitor_dpi_aware():
            user32 = ctypes.windll.user32
            cursor = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(cursor)):
                return None
            hwnd = user32.WindowFromPoint(cursor)
            if not hwnd:
                return None
            hwnd = user32.GetAncestor(hwnd, _GA_ROOT)
            if not hwnd or user32.IsIconic(hwnd):
                return None
            if _window_class_name(hwnd) in _SHELL_WINDOW_CLASSES:
                return None
            return _get_window_frame_rect(hwnd)
    except Exception as e:
        logger.warning("获取鼠标所在窗口边界失败: %s", e)
        return None


def grab_region(bbox: Optional[Rect]):
    """抓取 bbox 指定的屏幕区域（绝对物理像素，可跨屏），返回 PIL Image。

    统一走「整块虚拟桌面位图 + 手动裁剪」：`ImageGrab.grab(bbox=...)` 在多屏下
    只抓主屏位图、却按绝对坐标裁剪，副屏区域会被裁成一片黑。bbox 为 None 时
    返回整块虚拟桌面。
    """
    from PIL import ImageGrab

    with per_monitor_dpi_aware():
        full = ImageGrab.grab(all_screens=True)
        if bbox is None:
            return full

        user32 = ctypes.windll.user32
        origin_x = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        origin_y = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        left, top, right, bottom = bbox
        box = (
            max(0, left - origin_x),
            max(0, top - origin_y),
            min(full.width, right - origin_x),
            min(full.height, bottom - origin_y),
        )
        if box[2] - box[0] < _MIN_REGION_SIDE or box[3] - box[1] < _MIN_REGION_SIDE:
            logger.warning("截图区域完全越界（bbox=%s），回退整屏截图", bbox)
            return full
        if box != (left - origin_x, top - origin_y, right - origin_x, bottom - origin_y):
            logger.warning(
                "截图区域超出屏幕范围（bbox=%s, 虚拟桌面原点=(%d,%d)）",
                bbox, origin_x, origin_y,
            )
        return full.crop(box)


# ── 内部工具 ─────────────────────────────────────────────
def _monitor_rect(monitor) -> Optional[Rect]:
    """HMONITOR → 显示器全边界（物理像素）。"""
    user32 = ctypes.windll.user32
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
        return None
    rc = info.rcMonitor
    return (rc.left, rc.top, rc.right, rc.bottom)


def _get_window_frame_rect(hwnd) -> Optional[Rect]:
    """窗口的真实可见边界。

    优先 DWM 扩展边框（Win10 起 GetWindowRect 会带上不可见的调整边），
    失败则退回 GetWindowRect。
    """
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    try:
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(hwnd),
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr == 0 and rect.right > rect.left and rect.bottom > rect.top:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError):
        pass
    if user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def _window_class_name(hwnd) -> str:
    """窗口类名；失败返回空串。"""
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(
            ctypes.c_void_p(hwnd), buf, len(buf)
        )
        return buf.value
    except Exception:
        return ""
