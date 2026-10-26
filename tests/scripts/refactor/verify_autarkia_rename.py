"""验证 xiaoyou → autarkia 内部命名迁移（批次①显眼符号 + 批次④运行时 key）。

覆盖四件事：
1. 活代码零残留（docs/updates、Question_Reviewer、companion_data 等历史记录与运行时数据除外；
   批次②③范围的目录名/包名/同步通道形态不属本批次，白名单放行）
2. 新符号与新文件存在（AutarkiaError、AutarkiaSession、Autarkia.spec、--name=Autarkia）
3. 持久化边界兼容读旧行为（配置键迁移、multi_qq_config.json 原子写回、环境变量双读）
4. 前端 DesktopPet localStorage 迁移代码存在

运行：.venv/bin/python tests/scripts/refactor/verify_autarkia_rename.py
"""
import json
import os
import py_compile
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SELF_PATH = Path(__file__).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# 本批次必须清零的旧形态
RESIDUAL_PATTERNS = [
    "XiaoyouError", "XiaoyouSession", "XiaoyouCore", "Xiaoyou Core",
    "xiaoyou_ws_url", "xiaoyou_http_base_url", "xiaoyou_access_token",
    "XIAOYOU_ACCESS_TOKEN", "XIAOYOU_HTTP_BASE_URL", "XIAOYOU_WS_URL", "XIAOYOU_QQ_",
    "xiaoyou_pet_state_v1", "xiaoyou_pet_settings_v1",
    "xiaoyou_study_summary", "xiaoyou_main.log",
    "xiaoyou_test_storage_", "xiaoyou_test_chain_",
    # Windows 磁盘路径形态（批次③ Windows 半边已迁移，2026-10-23）
    r"AI\xiaoyou-core", "AI\\\\xiaoyou-core", "AI/xiaoyou-core",
    "/mnt/win_p4/AI/xiaoyou-core",
    # 磁盘产物与同步通道（2026-10-24 迁至 Autarkia-*）
    "xiaoyou-hub", "xiaoyou-sync", "xiaoyou-public", "xiaoyou-backup",
]
SCAN_DIRS = [
    "core", "config", "services", "routers", "scripts", "tools", "tests",
    "clients", "maintenance",
]
SCAN_EXTRA_FILES = [
    "launcher.py", "main.py", "server_run.py", "desktop_app.py", "build_exe.py",
    "readme.md", "readme.en.md", "UPDATES.md",
]
EXCLUDE_PARTS = (
    "__pycache__", "docs/updates", "Question_Reviewer", "companion_data",
    ".venv", "node_modules", ".git", "build", "artifacts",
)
EXCLUDE_FILES = {"uv.lock", "pyproject.toml", "multi_qq_config.json"}
# 运行时/历史存档数据，不属本批次
EXCLUDE_PATHS = {"core/character/configs/extra/2026/01/legacy.json"}
# 兼容读旧锚点：旧键/旧环境变量名作为 fallback 必须写进代码，命中不算残留
ALLOWED_LEGACY_FILES = {
    "config/settings_adapters.py",
    "clients/bots/qq/config.py",
    "clients/bots/qq/settings.py",
    "clients/bots/telegram/settings.py",
    "clients/frontend/aveline-web/src/components/DesktopPet.tsx",
}
SCAN_SUFFIXES = {
    ".py", ".ts", ".tsx", ".kt", ".md", ".sh", ".bat", ".yml", ".yaml", ".json", ".spec",
}
COMPILED_FILES = [
    "core/exceptions.py", "config/settings_adapters.py",
    "clients/bots/qq/config.py", "clients/bots/qq/settings.py",
    "clients/bots/telegram/settings.py",
]


def _iter_scan_files():
    for d in SCAN_DIRS:
        base = PROJECT_ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in SCAN_SUFFIXES:
                continue
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            if any(part in rel for part in EXCLUDE_PARTS):
                continue
            if p.name in EXCLUDE_FILES or rel.startswith("clients/bots/config/"):
                continue
            yield p


def check_no_residual() -> list:
    errors = []
    anchors = []
    files = list(_iter_scan_files())
    files += [PROJECT_ROOT / f for f in SCAN_EXTRA_FILES if (PROJECT_ROOT / f).exists()]
    for p in files:
        if p.resolve() == SELF_PATH:
            continue  # 脚本自身的 RESIDUAL_PATTERNS 字符串不算残留
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        if rel in EXCLUDE_PATHS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in RESIDUAL_PATTERNS:
            if pat in text:
                if rel in ALLOWED_LEGACY_FILES:
                    anchors.append(f"{rel}: {pat}")
                else:
                    errors.append(f"{rel} 残留旧形态: {pat}")
    for anchor in sorted(set(anchors)):
        print(f"  [兼容锚点] {anchor}")
    return errors


def check_new_symbols() -> list:
    errors = []
    exc_text = (PROJECT_ROOT / "core/exceptions.py").read_text(encoding="utf-8")
    if "class AutarkiaError(Exception)" not in exc_text:
        errors.append("core/exceptions.py 缺少 AutarkiaError 定义")
    if not (PROJECT_ROOT / "Autarkia.spec").exists():
        errors.append("Autarkia.spec 不存在")
    if (PROJECT_ROOT / "XiaoyouCore.spec").exists():
        errors.append("旧 XiaoyouCore.spec 仍存在")
    if "--name=Autarkia" not in (PROJECT_ROOT / "build_exe.py").read_text(encoding="utf-8"):
        errors.append("build_exe.py 未指向 --name=Autarkia")
    return errors


def check_compiled() -> list:
    errors = []
    for rel in COMPILED_FILES:
        try:
            py_compile.compile(str(PROJECT_ROOT / rel), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{rel} 语法错误: {e}")
    return errors


def test_config_migrate_legacy_keys() -> list:
    from clients.bots.qq.config import QQAdapterConfig, migrate_legacy_keys

    errors = []
    migrated = migrate_legacy_keys({"xiaoyou_ws_url": "ws://old", "role_id": "r1"})
    if migrated.get("autarkia_ws_url") != "ws://old" or "xiaoyou_ws_url" in migrated:
        errors.append(f"migrate_legacy_keys 未迁移 ws_url: {migrated}")
    both = migrate_legacy_keys(
        {"xiaoyou_access_token": "old", "autarkia_access_token": "new"}
    )
    if both.get("autarkia_access_token") != "new":
        errors.append(f"新旧键并存时应保留新值: {both}")
    cfg = QQAdapterConfig.from_dict({"xiaoyou_ws_url": "ws://legacy:8000/api/v1/ws"})
    if cfg.autarkia_ws_url != "ws://legacy:8000/api/v1/ws":
        errors.append(f"from_dict 未迁移旧键: {cfg.autarkia_ws_url}")
    if not cfg.autarkia_http_base_url:
        errors.append("from_dict 迁移后 http_base_url 未自动推导")
    return errors


def test_adapter_role_migration() -> list:
    from config.settings_adapters import _migrate_legacy_adapter_role

    errors = []
    role = _migrate_legacy_adapter_role(
        {"xiaoyou_ws_url": "ws://a", "xiaoyou_access_token": "tok", "role_id": "r"}
    )
    if role.get("autarkia_ws_url") != "ws://a" or role.get("autarkia_access_token") != "tok":
        errors.append(f"角色配置旧键未迁移: {role}")
    if "xiaoyou_ws_url" in role or "xiaoyou_access_token" in role:
        errors.append(f"迁移后旧键未清除: {role}")
    return errors


def test_multi_qq_file_migration() -> list:
    from config.settings_adapters import _migrate_legacy_multi_qq_file

    errors = []
    with tempfile.TemporaryDirectory(prefix="autarkia_test_rename_") as tmp:
        json_path = Path(tmp) / "multi_qq_config.json"
        raw = {"aveline": {"role_id": "aveline", "xiaoyou_ws_url": "ws://legacy"}}
        json_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        migrated = _migrate_legacy_multi_qq_file(raw, json_path)
        if migrated["aveline"].get("autarkia_ws_url") != "ws://legacy":
            errors.append(f"文件迁移结果错误: {migrated}")
        on_disk = json.loads(json_path.read_text(encoding="utf-8"))
        if on_disk["aveline"].get("autarkia_ws_url") != "ws://legacy":
            errors.append(f"迁移未原子写回文件: {on_disk}")
        if "xiaoyou_ws_url" in on_disk["aveline"]:
            errors.append(f"写回文件仍含旧键: {on_disk}")
        stable = _migrate_legacy_multi_qq_file(migrated, json_path)
        if stable != migrated:
            errors.append("迁移应幂等")
    return errors


def test_env_first() -> list:
    from clients.bots.qq.settings import _env_first

    errors = []
    new_name, old_name = "AUTARKIA_QQ_MASTER_ID", "XIAOYOU_QQ_MASTER_ID"
    old_backup, new_backup = os.environ.pop(old_name, None), os.environ.pop(new_name, None)
    try:
        os.environ[old_name] = "from-old"
        if _env_first(new_name, old_name) != "from-old":
            errors.append("仅旧环境变量时应读到旧值")
        os.environ[new_name] = "from-new"
        if _env_first(new_name, old_name) != "from-new":
            errors.append("新环境变量应优先于旧变量")
        os.environ.pop(new_name)
        os.environ.pop(old_name)
        if _env_first(new_name, old_name) is not None:
            errors.append("未设置时应返回 None")
    finally:
        for name, val in ((old_name, old_backup), (new_name, new_backup)):
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val
    return errors


def check_qq_settings_env_fallback() -> list:
    errors = []
    text = (PROJECT_ROOT / "clients/bots/qq/settings.py").read_text(encoding="utf-8")
    if text.count("_env_first(") < 20:
        errors.append("settings.py 环境变量双读调用数量异常")
    if '"XIAOYOU_QQ_MASTER_ID"' not in text:
        errors.append("settings.py 缺少旧变量名 fallback")
    mappings = (PROJECT_ROOT / "clients/bots/qq/config.py").read_text(encoding="utf-8")
    if '"XIAOYOU_ACCESS_TOKEN"' not in mappings:
        errors.append("config.py env 映射缺少旧变量名 fallback")
    return errors


def check_desktop_pet_migration() -> list:
    errors = []
    rel = "clients/frontend/aveline-web/src/components/DesktopPet.tsx"
    text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    if "migrateLegacyPetKeys();" not in text:
        errors.append("DesktopPet.tsx 缺少迁移调用")
    if "'autarkia_pet_state_v1'" not in text or "'autarkia_pet_settings_v1'" not in text:
        errors.append("DesktopPet.tsx 新 localStorage 键缺失")
    if "'xiaoyou_pet_state_v1'" not in text:
        errors.append("DesktopPet.tsx 缺少旧键迁移来源")
    return errors


def main() -> int:
    checks = [
        ("残留扫描", check_no_residual),
        ("新符号存在", check_new_symbols),
        ("语法编译", check_compiled),
        ("qq.config 键迁移", test_config_migrate_legacy_keys),
        ("settings_adapters 角色迁移", test_adapter_role_migration),
        ("multi_qq_config.json 写回迁移", test_multi_qq_file_migration),
        ("环境变量双读", test_env_first),
        ("env fallback 静态检查", check_qq_settings_env_fallback),
        ("DesktopPet localStorage 迁移", check_desktop_pet_migration),
    ]
    failed = False
    for name, fn in checks:
        try:
            errors = fn()
        except Exception as e:  # noqa: BLE001 —— 验证脚本需吞掉导入期异常并报告
            errors = [f"检查执行异常: {type(e).__name__}: {e}"]
        status = "PASS" if not errors else "FAIL"
        print(f"[{status}] {name}")
        for err in errors:
            print(f"  - {err}")
            failed = True
    if failed:
        print("\n验证失败：存在未迁移残留或兼容逻辑缺陷")
        return 1
    print("\n验证通过：xiaoyou→autarkia 命名迁移完成，持久化边界兼容读旧生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
