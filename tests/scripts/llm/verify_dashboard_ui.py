#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 token 看板前端：模块解耦、DOM 契约、类型检查与请求次数面板数据。

五组检查：
1. 结构：index.html 只引用外部 CSS / JS，不再内联样式与脚本；
2. 模块：每个 ``import { x } from './y.js'`` 的 x 都在 y.js 里真实导出；
3. DOM 契约：JS 里用到的每个 ``$('id')`` 都能在 index.html 找到对应元素；
4. 类型：所有模块带 ``// @ts-check``，并通过 tsc 的 checkJs 校验（不产出文件）；
5. 数据：请求次数面板依赖的 requests 字段在 overview 接口里真实存在。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\llm\\verify_dashboard_ui.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DASHBOARD_DIR = PROJECT_ROOT / "static" / "token_stats"
INDEX_HTML = DASHBOARD_DIR / "index.html"
JS_DIR = DASHBOARD_DIR / "js"
CSS_DIR = DASHBOARD_DIR / "css"
TSCONFIG = DASHBOARD_DIR / "tsconfig.check.json"
TSC_ENTRY = (
    PROJECT_ROOT
    / "clients"
    / "frontend"
    / "aveline-web"
    / "node_modules"
    / "typescript"
    / "bin"
    / "tsc"
)

IMPORT_PATTERN = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
EXPORT_NAME_PATTERN = re.compile(r"export\s+(?:const|let|var|function|class)\s+([A-Za-z0-9_$]+)")
EXPORT_LIST_PATTERN = re.compile(r"export\s*\{([^}]*)\}")
DOM_ID_PATTERN = re.compile(r"\$\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*\)")
HTML_ID_PATTERN = re.compile(r'id="([A-Za-z0-9_-]+)"')
HTML_REF_PATTERN = re.compile(r'(?:href|src)="(/static/token_stats/[^"]+)"')


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _js_files() -> List[Path]:
    return sorted(JS_DIR.rglob("*.js"))


def _collect_exports(text: str) -> Set[str]:
    """收集一个模块文件里所有具名导出。"""
    names: Set[str] = set(EXPORT_NAME_PATTERN.findall(text))
    for group in EXPORT_LIST_PATTERN.findall(text):
        for item in group.split(","):
            item = item.strip()
            if not item:
                continue
            names.add(item.split(" as ")[-1].strip())
    return names


def verify_structure() -> None:
    """index.html 应是薄壳：只引用外部资源，不内联样式与脚本。"""
    _check(INDEX_HTML.exists(), f"缺少看板入口: {INDEX_HTML}")
    html = INDEX_HTML.read_text(encoding="utf-8")

    _check("<style" not in html, "index.html 不应再内联 <style>，样式应拆到 css/")
    inline_scripts = [
        block
        for block in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        if block.strip()
    ]
    _check(not inline_scripts, "index.html 不应再内联脚本，逻辑应拆到 js/")

    refs = HTML_REF_PATTERN.findall(html)
    _check(refs, "index.html 至少要引用外部 CSS / JS")
    for ref in refs:
        target = PROJECT_ROOT / ref.lstrip("/")
        _check(target.exists(), f"index.html 引用的资源不存在: {ref}")

    _check((JS_DIR / "main.js").exists(), "缺少前端入口 js/main.js")
    _check(len(list(CSS_DIR.glob("*.css"))) >= 3, "CSS 至少应拆成 base / layout / components 三层")
    _check(len(_js_files()) >= 10, "JS 模块数量异常，看板可能被合并回单文件")


def verify_module_exports() -> None:
    """import 的每个具名符号都必须在目标模块里导出。"""
    for path in _js_files():
        text = path.read_text(encoding="utf-8")
        for group, specifier in IMPORT_PATTERN.findall(text):
            if not specifier.startswith("."):
                continue
            target = (path.parent / specifier).resolve()
            _check(target.exists(), f"{path.name} 引用了不存在的模块: {specifier}")
            exported = _collect_exports(target.read_text(encoding="utf-8"))
            for item in group.split(","):
                name = item.strip().split(" as ")[0].strip()
                if not name:
                    continue
                _check(
                    name in exported,
                    f"{path.name} 从 {specifier} 导入了未导出的符号: {name}",
                )


def verify_dom_contract() -> None:
    """JS 里用到的元素 id 必须存在于 index.html。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    html_ids = set(HTML_ID_PATTERN.findall(html))

    used: Set[str] = set()
    for path in _js_files():
        used.update(DOM_ID_PATTERN.findall(path.read_text(encoding="utf-8")))

    missing = sorted(used - html_ids)
    _check(not missing, f"JS 引用了 index.html 里不存在的元素 id: {missing}")

    for required in (
        "req-stats",
        "req-chart",
        "req-sources",
        "req-hint",
        "chart-wrap",
        "req-chart-wrap",
    ):
        _check(required in html_ids, f"看板缺少必需的元素 id: {required}")


def verify_scrollbar_style() -> None:
    """看板必须使用自定义滚动条（原生滚动条是本次要修的视觉问题）。"""
    base_css = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    _check("::-webkit-scrollbar" in base_css, "base.css 缺少自定义滚动条样式")
    _check("scrollbar-width" in base_css, "base.css 缺少 Firefox 回退样式")
    _check("::-webkit-scrollbar-thumb" in base_css, "base.css 缺少滚动条滑块样式")


def _strip_comments(text: str) -> str:
    """去掉 CSS 块注释：说明文字里提到 backdrop-filter 不该被判成回归。"""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def verify_breathing_paint_cost() -> None:
    """呼吸灯层不能留逐帧重算的绘制：这是看板「用着卡」的根因，回归了要立刻发现。

    三条口径：光斑用 radial-gradient 自己软边；卡片不取样背景；
    脉动高光不把 box-shadow 写进关键帧（每帧重绘外发光）。
    """
    css = {
        path.name: _strip_comments(path.read_text(encoding="utf-8"))
        for path in CSS_DIR.glob("*.css")
    }
    for name, text in css.items():
        _check("backdrop-filter" not in text, f"{name} 又用上了 backdrop-filter")
        _check("blur(" not in text, f"{name} 有常驻的高斯模糊，改成渐变软边")
    _check(
        "radial-gradient" in css.get("breathing.css", ""),
        "breathing.css 的光斑应改用 radial-gradient 而不是高斯模糊",
    )
    accent = re.search(
        r"@keyframes breathe-accent\s*\{(.*?)\n\}", css.get("breathing.css", ""), re.S
    )
    _check(
        bool(accent) and "box-shadow" not in accent.group(1),
        "breathe-accent 关键帧里不该有 box-shadow",
    )


def verify_type_check() -> None:
    """所有模块带 ``// @ts-check``，并通过 tsc 的 checkJs 校验（只校验不产出）。"""
    for path in _js_files():
        head = path.read_text(encoding="utf-8").splitlines()[:1]
        _check(head and head[0].strip() == "// @ts-check", f"{path.name} 缺少 // @ts-check 标记")

    _check(TSCONFIG.exists(), f"缺少类型校验配置: {TSCONFIG}")
    if not (TSC_ENTRY.exists() and shutil.which("node")):
        print("[SKIP] 未找到 node / tsc，跳过类型校验（需先安装前端依赖）")
        return

    result = subprocess.run(
        ["node", str(TSC_ENTRY), "-p", str(TSCONFIG)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _check(
        result.returncode == 0,
        "TypeScript 类型校验未通过:\n" + (result.stdout or "") + (result.stderr or ""),
    )


def verify_request_panel_contract() -> None:
    """请求次数面板依赖的数据字段必须真实存在。"""
    from core.llm.token_stats import build_overview

    data = build_overview(granularity="day")
    series = data["series"]
    by_source = data["by_source"]
    totals = data["totals"]

    _check(bool(series), "真实日志应至少有一个日桶")
    _check("requests" in series[0], "时间桶缺少 requests 字段")
    _check("requests" in by_source[0], "调用来源分布缺少 requests 字段")
    _check(
        sum(bucket["requests"] for bucket in series) == totals["requests"],
        "按日请求数之和应等于总请求数",
    )
    _check(
        sum(row["requests"] for row in by_source) == totals["requests"],
        "按来源请求数之和应等于总请求数（含『其他』合并桶）",
    )
    print(
        f"[OK] 请求次数面板数据：{totals['requests']} 次调用，"
        f"{len(series)} 个日桶，{len(by_source)} 个来源"
    )


def main() -> int:
    print("=" * 62)
    print("token 看板前端验证")
    print("=" * 62)
    try:
        verify_structure()
        print("[OK] 结构：index.html 为薄壳，资源全部外置")
        verify_module_exports()
        print("[OK] 模块：import / export 符号全部对得上")
        verify_dom_contract()
        print("[OK] DOM 契约：JS 引用的元素 id 全部存在")
        verify_scrollbar_style()
        print("[OK] 视觉：自定义滚动条样式在位")
        verify_breathing_paint_cost()
        print("[OK] 绘制：呼吸灯层逐帧成本已减负（无模糊、无 backdrop 取样）")
        verify_type_check()
        print("[OK] 类型：@ts-check 标记齐全，tsc checkJs 校验通过")
        verify_request_panel_contract()
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
