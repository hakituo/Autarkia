"""设备控制工具基类

提供:
- _execute() 封装 DeviceCommandBridge 调用 + 结果格式化
权限校验 _is_master() 已收拢到 BaseTool（唯一实现），此处不再重复定义。
"""

from typing import Any, Dict

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("device_tools")


class DeviceToolBase(BaseTool):
    """设备控制工具基类, 所有 device 工具继承此类"""

    category = "device"
    # 设备控制类工具默认不启用, 仅 Master 可用
    enabled_by_default = True

    async def _execute(
        self,
        command: str,
        args: Dict[str, Any],
        timeout: float = 30.0,
    ) -> str:
        """下发设备指令并格式化结果

        Args:
            command: 指令名 (如 "force_stop_app")
            args: 指令参数
            timeout: 超时秒数

        Returns:
            格式化的结果字符串 (给 LLM 看)
        """
        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        user_id = self._get_ctx("user_id")

        from core.services.device_command import get_device_command_bridge

        bridge = get_device_command_bridge()
        result = await bridge.execute(command, args, user_id, timeout=timeout)

        status = result.get("status")
        if status == "success":
            data = result.get("result", {})
            return self._format_success(data)
        else:
            error = result.get("error", "未知错误")
            return f"执行失败: {error}"

    def _format_success(self, data: Dict[str, Any]) -> str:
        """格式化成功结果, 子类可覆盖以自定义输出"""
        summary = data.get("summary")
        if summary:
            return str(summary)
        return str(data)
