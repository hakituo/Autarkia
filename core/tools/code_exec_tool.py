"""RunCodeTool —— 在沙箱中执行 Python 代码。

这是"能动手做事"的基础能力：计算、数据处理、用 matplotlib 出图、
生成文件。执行在隔离子进程里完成，代码先过 AST 静态检查。

返回结构固定为 JSON（``type=code_exec_result``），便于上层
（``handler_tool_calls``）识别并提取产物路径回传给前端。
"""

from __future__ import annotations

import json
from typing import List

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("RunCodeTool")


class RunCodeInput(BaseModel):
    code: str = Field(
        description=(
            "要执行的完整 Python 代码。可以 print 输出结果，"
            "也可以用 matplotlib 画图（图片会作为产物自动返回）。"
        )
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=120,
        description="最长执行秒数，默认 30，最大 120。",
    )


class RunCodeTool(BaseTool):
    name = "run_code"
    description = (
        "在隔离沙箱中执行 Python 代码并返回运行输出，用于数学计算、数据分析、"
        "以及用 matplotlib 绘制图表。可用库包括 numpy / scipy / pandas / "
        "matplotlib / PIL 和安全标准库子集。"
        "沙箱内不能访问文件系统、网络或系统命令，也不能读写沙箱外的文件。"
        "代码里用 plt.savefig('名字.png') 保存的图片会作为产物返回给用户。"
    )
    short_description = "执行 Python 代码并返回输出"
    category = "execution"
    args_schema = RunCodeInput
    enabled_by_default = True

    async def _run(self, code: str, timeout: int = 30) -> str:
        from core.services.sandbox import check_code, run_code

        ok, errors = check_code(code)
        if not ok:
            logger.info("run_code 被静态检查拒绝: %s", errors)
            return json.dumps(
                {
                    "type": "code_exec_result",
                    "ok": False,
                    "rejected": True,
                    "errors": errors,
                    "hint": "请修改代码后重试：只能使用白名单内的库，不能调用 open/eval/exec 或访问 os/sys/subprocess 等模块。",
                },
                ensure_ascii=False,
            )

        result = await run_code(code, timeout=timeout)

        if result.artifacts:
            from core.services.sandbox.artifacts import record_artifacts

            record_artifacts(result.artifacts)

        if result.error and not result.timed_out:
            return json.dumps(
                {
                    "type": "code_exec_result",
                    "ok": False,
                    "errors": [result.error],
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "type": "code_exec_result",
                "ok": result.ok,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "artifacts": result.artifacts,
                "errors": [result.error] if result.error else [],
            },
            ensure_ascii=False,
        )


def format_result_for_model(payload: dict) -> str:
    """把 ``code_exec_result`` 压成给模型看的简短文本，避免 token 浪费。"""
    if not isinstance(payload, dict):
        return str(payload)
    if payload.get("rejected"):
        return "代码被安全检查拒绝：" + "；".join(payload.get("errors") or [])
    if payload.get("timed_out"):
        return "代码执行超时，已终止。"
    parts: List[str] = []
    stdout = str(payload.get("stdout") or "").strip()
    stderr = str(payload.get("stderr") or "").strip()
    artifacts = payload.get("artifacts") or []
    if stdout:
        parts.append(f"标准输出：\n{stdout}")
    if stderr:
        parts.append(f"标准错误：\n{stderr}")
    if artifacts:
        names = "、".join(str(a).replace("\\", "/").split("/")[-1] for a in artifacts)
        parts.append(f"已生成文件（{len(artifacts)} 个）：{names}")
    if not payload.get("ok"):
        parts.append("执行未成功，请检查代码。")
    if not parts:
        parts.append("执行完成，无输出。")
    return "\n".join(parts)
