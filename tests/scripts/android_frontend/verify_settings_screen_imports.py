"""验证设置首页使用的 Compose 尺寸扩展已正确导入。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/settings/SettingsHomePage.kt"
)


def main() -> None:
    """检查 padding 与 dp 的导入及调用，防止相同编译错误回归。

    设置页已从五 Tab 改为分组列表，实际排版落在 SettingsHomePage；
    断言目标跟着搬家，避免继续守着只做页面分发的 SettingsScreenV2。
    """
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "import androidx.compose.foundation.layout.padding",
        "import androidx.compose.ui.unit.dp",
        ".padding(horizontal = 20.dp)",
    )
    missing = [fragment for fragment in required if fragment not in source]
    if missing:
        raise AssertionError(f"SettingsHomePage 缺少必要实现: {missing}")
    print("PASS: SettingsHomePage 的 padding 与 dp 导入完整。")


if __name__ == "__main__":
    main()
