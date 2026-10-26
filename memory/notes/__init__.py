"""派生笔记库（v3 F3 WP2）：按 segment 原子替换，不写进旧加权记忆池。"""

from .store import NoteStore, ReplaceResult

__all__ = ["NoteStore", "ReplaceResult"]
