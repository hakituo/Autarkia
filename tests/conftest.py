"""
pytest 配置文件

配置测试发现路径和异步测试支持
使用 pytest-asyncio 处理异步测试
"""
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _install_public_slice_stubs() -> None:
    """公开切片专用：为未随发布外发的模块安装占位壳。

    公开仓库不含角色资料（core/character）、角色日程引擎与私密 prompt 装配层，
    但这些模块被大量单元测试引用。这里用 MetaPathFinder 注入轻量占位模块，
    让测试可以正常导入与收集；被测逻辑本身仍走公开仓库里的真实实现。
    私有主仓库中这些目录真实存在，本函数不会生效。
    """
    if (PROJECT_ROOT / "core" / "character").exists():
        return

    import importlib.abc
    import importlib.machinery
    import types
    from unittest.mock import MagicMock

    stub_prefixes = (
        "core.character",
        "core.services.character_daily",
        "core.services.dual_role",
        "core.agents.chat_agent_components.persona_system.prompt",
        "core.services.study.signal_detector",
        "config.character_daily_config",
        "clients.bots.qq.media_tags",
        "tools",
        "scripts.import",
    )

    class _StubModule(types.ModuleType):
        """占位模块：任意属性访问都返回可调用的 MagicMock。"""

        def __getattr__(self, name):
            if name == "__file__":
                return f"<public-stub:{self.__name__}>"
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            value = MagicMock(name=f"{self.__name__}.{name}")
            setattr(self, name, value)
            return value

    class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if any(
                fullname == prefix or fullname.startswith(prefix + ".")
                for prefix in stub_prefixes
            ):
                return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
            return None

        def create_module(self, spec):
            module = _StubModule(spec.name)
            module.__path__ = []
            module.__file__ = f"<public-stub:{spec.name}>"
            return module

        def exec_module(self, module):
            return None

    sys.meta_path.insert(0, _StubFinder())


_install_public_slice_stubs()


def pytest_configure(config):
    """pytest 配置钩子"""
    # 配置测试发现路径
    config.addinivalue_line(
        "markers", "asyncio: mark test as an asyncio test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "gpu: mark test as requiring GPU"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


def pytest_collection_modifyitems(config, items):
    """
    测试收集后处理钩子
    为测试添加默认标记
    """
    # 根据文件路径自动添加标记
    for item in items:
        # 单元测试
        if "unit" in str(item.fspath):
            item.add_marker("unit")
        # 集成测试
        elif "integration" in str(item.fspath):
            item.add_marker("integration")
        # 压力测试
        elif "stress" in str(item.fspath):
            item.add_marker("slow")
        # 调度器测试
        elif "scheduler" in str(item.fspath):
            item.add_marker("integration")
