from typing import List, Dict, Any, Optional
import time
import uuid
from collections import deque


class NotificationManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NotificationManager, cls).__new__(cls)
            cls._instance.notifications = {}  # user_id -> deque of notifications
            cls._instance.last_poll_time = {}  # user_id -> timestamp
        return cls._instance

    def has_active_connections(self, timeout: float = 60.0) -> bool:
        """检查是否有活跃的轮询连接"""
        now = time.time()
        for last_poll in self.last_poll_time.values():
            if now - last_poll < timeout:
                return True
        return False

    def add_notification(
        self,
        user_id: str,
        type: str,
        title: str,
        content: str,
        payload: Dict[str, Any] = None,
    ):
        if user_id not in self.notifications:
            self.notifications[user_id] = deque(maxlen=50)

        notification = {
            "id": str(uuid.uuid4()),
            "type": type,  # "text", "image", "voice", "vocabulary"
            "title": title,
            "content": content,
            "payload": payload or {},
            "timestamp": time.time(),
            "read": False,
        }
        self.notifications[user_id].append(notification)
        return notification

    def peek_notifications(self, user_id: str) -> List[Dict[str, Any]]:
        """非破坏性读取通知（供通知中心展示，不清空队列）。

        ``get_pending_notifications`` 是「拉一次就消费」的推送语义，直接拿来渲染
        通知中心会导致刷新页面后列表变空。通知中心需要稳定的历史视图，因此单独
        提供只读入口，并同步刷新活跃时间，避免被 ``has_active_connections`` 误判。
        """
        self.last_poll_time[user_id] = time.time()
        return [dict(item) for item in self.notifications.get(user_id, [])]

    def mark_read(
        self, user_id: str, notification_ids: Optional[List[str]] = None
    ) -> int:
        """把通知标记为已读；不传 ID 表示全部已读，返回本次标记条数。"""
        items = self.notifications.get(user_id)
        if not items:
            return 0
        targets = {str(i) for i in (notification_ids or []) if str(i).strip()}
        marked = 0
        for item in items:
            if item.get("read"):
                continue
            if targets and str(item.get("id")) not in targets:
                continue
            item["read"] = True
            marked += 1
        return marked

    def unread_count(self, user_id: str) -> int:
        """未读通知条数（通知中心徽章用）。"""
        return sum(
            1 for item in self.notifications.get(user_id, []) if not item.get("read")
        )

    def get_pending_notifications(self, user_id: str) -> List[Dict[str, Any]]:
        """获取并清除待处理的通知"""
        self.last_poll_time[user_id] = time.time()
        if user_id not in self.notifications:
            return []

        # Return all unread (in this simple version, we just return all and clear, or return unread)
        # For polling, usually we want to "pop" them or mark them as read.
        # Let's pop them to ensure they are only delivered once per poll cycle.

        results = []
        while self.notifications[user_id]:
            results.append(self.notifications[user_id].popleft())

        return results


def get_notification_manager():
    return NotificationManager()
