"""
测试 image_models API 修复
验证 dashboard 的 image_models 计数逻辑与 list_models 返回结构
"""
import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root_dir))


async def test_image_models_api():
    """list_models 应返回非 None 的结构化字典。"""
    from core.image.image_manager import ImageManager

    manager = ImageManager()
    result = await manager.list_models()

    assert result is not None, "list_models 不应返回 None"
    assert isinstance(result, dict), "list_models 应返回字典"
    for group in ("sd15", "sdxl"):
        if group in result:
            assert isinstance(result[group], dict), f"{group} 分组应为字典"


def test_dashboard_handler():
    """测试 dashboard handler 的 image_models 计数（真实实现，非本地副本）。"""
    from clients.bots.handlers.dashboard import _count_image_models

    test_cases = [
        (None, 0),
        ({}, 0),
        ({"sd15": {"checkpoints": [], "loras": []}}, 0),
        ({"sd15": {"checkpoints": [{"name": "test"}], "loras": []}}, 1),
        ({"sdxl": {"models": [{"name": "a"}, {"name": "b"}]}}, 2),
        ({"sd15": {"checkpoints": [1, 2, 3], "loras": [4, 5]}}, 5),
    ]
    for input_data, expected in test_cases:
        assert _count_image_models(input_data) == expected, f"输入={input_data} 期望 {expected}"


if __name__ == "__main__":
    asyncio.run(test_image_models_api())
    test_dashboard_handler()
    print("image_models 测试通过")
