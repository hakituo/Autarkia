"""
测试多API key配置功能

验证：
1. 多API key配置加载
2. 模型注册
3. 模型路径解析
"""

import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def test_cloud_provider_key_config():
    """测试CloudProviderKeyConfig类"""
    from config.settings_model import CloudProviderKeyConfig
    
    # 测试基本配置
    config = CloudProviderKeyConfig(
        key_alias="qqbot1",
        api_key="sk-test-key",
        api_key_env="DEEPSEEK_API_KEY_QQBOT1",
        base_url="https://api.deepseek.com/chat/completions",
        models=["deepseek-v4-pro", "deepseek-v4-flash"],
        thinking_enabled=True,
        reasoning_effort="high",
    )
    
    assert config.key_alias == "qqbot1"
    assert config.api_key == "sk-test-key"
    assert config.api_key_env == "DEEPSEEK_API_KEY_QQBOT1"
    assert len(config.models) == 2
    assert "deepseek-v4-pro" in config.models
    print("✓ CloudProviderKeyConfig 测试通过")


def test_load_cloud_provider_keys_from_env():
    """测试从环境变量加载多API key配置"""
    from config.settings_model import _load_cloud_provider_keys_from_env
    
    # 设置测试环境变量
    os.environ["DEEPSEEK_API_KEY"] = "sk-default-key"
    os.environ["DEEPSEEK_API_KEY_QQBOT1"] = "sk-qqbot1-key"
    os.environ["DEEPSEEK_API_KEY_QQBOT2"] = "sk-qqbot2-key"
    
    try:
        result = _load_cloud_provider_keys_from_env()
        
        # 验证deepseek配置
        assert "deepseek" in result
        deepseek_configs = result["deepseek"]
        
        # 验证默认key
        assert "default" in deepseek_configs
        assert deepseek_configs["default"].api_key == "sk-default-key"
        
        # 验证qqbot1
        assert "qqbot1" in deepseek_configs
        assert deepseek_configs["qqbot1"].api_key == "sk-qqbot1-key"
        assert deepseek_configs["qqbot1"].key_alias == "qqbot1"
        
        # 验证qqbot2
        assert "qqbot2" in deepseek_configs
        assert deepseek_configs["qqbot2"].api_key == "sk-qqbot2-key"
        assert deepseek_configs["qqbot2"].key_alias == "qqbot2"
        
        print("✓ _load_cloud_provider_keys_from_env 测试通过")
    finally:
        # 清理测试环境变量
        del os.environ["DEEPSEEK_API_KEY"]
        del os.environ["DEEPSEEK_API_KEY_QQBOT1"]
        del os.environ["DEEPSEEK_API_KEY_QQBOT2"]


def test_model_path_parsing():
    """测试模型路径解析"""
    
    # 测试传统格式
    path1 = "cloud:deepseek:deepseek-v4-pro"
    parts1 = path1.split(":")
    assert len(parts1) == 3
    assert parts1[0] == "cloud"
    assert parts1[1] == "deepseek"
    assert parts1[2] == "deepseek-v4-pro"
    
    # 测试新格式
    path2 = "cloud:deepseek:qqbot1:deepseek-v4-pro"
    parts2 = path2.split(":")
    assert len(parts2) == 4
    assert parts2[0] == "cloud"
    assert parts2[1] == "deepseek"
    assert parts2[2] == "qqbot1"
    assert parts2[3] == "deepseek-v4-pro"
    
    print("✓ 模型路径解析测试通过")


def test_model_path_generation():
    """测试模型路径生成"""
    from clients.bots.handlers.config import ConfigHandler
    
    # 创建一个模拟的adapter
    class MockAdapter:
        pass
    
    handler = ConfigHandler(MockAdapter())
    
    # 测试传统格式
    hint1 = handler.make_cloud_model_hint("deepseek", "deepseek-v4-pro")
    assert hint1 == "cloud:deepseek:deepseek-v4-pro"
    
    # 测试新格式
    hint2 = handler.make_cloud_model_hint("deepseek", "deepseek-v4-pro", "qqbot1")
    assert hint2 == "cloud:deepseek:qqbot1:deepseek-v4-pro"
    
    # 测试空值
    hint3 = handler.make_cloud_model_hint("", "deepseek-v4-pro")
    assert hint3 == ""
    
    hint4 = handler.make_cloud_model_hint("deepseek", "")
    assert hint4 == ""
    
    hint5 = handler.make_cloud_model_hint("local", "model")
    assert hint5 == ""
    
    print("✓ 模型路径生成测试通过")


def test_cloud_router_select_client():
    """测试CloudRouterLLMModule的_select_client方法"""
    from core.llm import CloudRouterLLMModule
    
    # 创建模拟的客户端
    class MockClient:
        def __init__(self, name):
            self.name = name
        
        def get_status(self):
            return {"name": self.name}
    
    # 创建客户端映射
    clients = {
        "deepseek": MockClient("deepseek-default"),
        "deepseek:qqbot1": MockClient("deepseek-qqbot1"),
        "deepseek:qqbot2": MockClient("deepseek-qqbot2"),
    }
    
    router = CloudRouterLLMModule(clients, default_provider="deepseek")
    
    # 测试传统格式
    client1, kwargs1 = router._select_client("cloud:deepseek:deepseek-v4-pro", {})
    assert client1 is not None
    assert client1.name == "deepseek-default"
    assert kwargs1.get("model") == "deepseek-v4-pro"
    
    # 测试新格式
    client2, kwargs2 = router._select_client("cloud:deepseek:qqbot1:deepseek-v4-pro", {})
    assert client2 is not None
    assert client2.name == "deepseek-qqbot1"
    assert kwargs2.get("model") == "deepseek-v4-pro"
    
    # 测试另一个key
    client3, kwargs3 = router._select_client("cloud:deepseek:qqbot2:deepseek-v4-flash", {})
    assert client3 is not None
    assert client3.name == "deepseek-qqbot2"
    assert kwargs3.get("model") == "deepseek-v4-flash"
    
    print("✓ CloudRouterLLMModule._select_client 测试通过")


def test_active_tokens():
    """测试_active_tokens方法"""
    from clients.bots.handlers.resources import ResourceHandler
    
    # 创建一个模拟的adapter
    class MockAdapter:
        pass
    
    handler = ResourceHandler(MockAdapter())
    
    # 测试传统格式
    current1 = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "path": "cloud:deepseek:deepseek-v4-pro",
    }
    tokens1 = handler._active_tokens(current1)
    assert "deepseek" in tokens1
    assert "deepseek-v4-pro" in tokens1
    assert "cloud:deepseek:deepseek-v4-pro" in tokens1
    
    # 测试新格式
    current2 = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "path": "cloud:deepseek:qqbot1:deepseek-v4-pro",
    }
    tokens2 = handler._active_tokens(current2)
    assert "deepseek" in tokens2
    assert "deepseek-v4-pro" in tokens2
    assert "cloud:deepseek:qqbot1:deepseek-v4-pro" in tokens2
    
    print("✓ _active_tokens 测试通过")


def test_is_active_model_entry():
    """测试_is_active_model_entry方法"""
    from clients.bots.handlers.resources import ResourceHandler
    
    # 创建一个模拟的adapter
    class MockAdapter:
        pass
    
    handler = ResourceHandler(MockAdapter())
    
    # 测试传统格式
    entry1 = {
        "id": "deepseek-v4-pro",
        "name": "deepseek-v4-pro",
        "path": "cloud:deepseek:deepseek-v4-pro",
        "provider": "deepseek",
    }
    active_tokens1 = {"deepseek", "deepseek-v4-pro", "cloud:deepseek:deepseek-v4-pro"}
    assert handler._is_active_model_entry(entry1, active_tokens1) == True
    
    # 测试新格式
    entry2 = {
        "id": "deepseek-v4-pro (qqbot1)",
        "name": "deepseek-v4-pro (qqbot1)",
        "path": "cloud:deepseek:qqbot1:deepseek-v4-pro",
        "provider": "deepseek",
    }
    active_tokens2 = {"deepseek", "deepseek-v4-pro", "cloud:deepseek:qqbot1:deepseek-v4-pro"}
    assert handler._is_active_model_entry(entry2, active_tokens2) == True
    
    print("✓ _is_active_model_entry 测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("开始测试多API key配置功能")
    print("=" * 50)
    
    try:
        test_cloud_provider_key_config()
        test_load_cloud_provider_keys_from_env()
        test_model_path_parsing()
        test_model_path_generation()
        test_cloud_router_select_client()
        test_active_tokens()
        test_is_active_model_entry()
        
        print("=" * 50)
        print("✓ 所有测试通过！")
        print("=" * 50)
        return True
    except AssertionError as e:
        print(f"✗ 测试失败: {e}")
        return False
    except Exception as e:
        print(f"✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
