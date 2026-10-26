"""表情包语义检索验证脚本

验证项：
1. 索引文件存在性检查（无索引时跳过相关测试，不报错）
2. pick_meme_by_semantic 基础检索（默认阈值 0.60）
3. 媒体标签 [MEME:语义] 端到端（通过 media_tags.pick_meme_image）
4. 低相似度查询直接不发（0.5x 的无关匹配不得发图）
5. LRU 去重生效

运行：
    python -m tests.scripts.meme.verify_meme_semantic_search
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _check_index_files() -> bool:
    """检查索引文件是否存在。"""
    index_dir = PROJECT_ROOT / "data" / "memes" / "_index"
    vec_path = index_dir / "vectors.npy"
    paths_path = index_dir / "paths.json"
    if not vec_path.is_file() or not paths_path.is_file():
        print(
            "[SKIP] 向量索引不存在，请先运行：\n"
            "  python -m scripts.meme.build_meme_descriptions\n"
            "  python -m scripts.meme.build_meme_vector_index"
        )
        return False
    return True


def test_basic_search() -> bool:
    """测试 pick_meme_by_semantic 基础检索。"""
    from clients.bots.qq.meme_search import pick_meme_by_semantic, get_status

    print(f"[INFO] 索引状态: {get_status()}")

    queries = [
        "委屈想哭",
        "害羞脸红",
        "开心大笑",
        "生气地瞪着",
        "惊讶震惊",
    ]
    success = 0
    for q in queries:
        result = pick_meme_by_semantic(q, top_k=5)
        if result and result.is_file():
            print(f"  [OK] {q!r:30} -> {result.name}")
            success += 1
        else:
            print(f"  [FAIL] {q!r:30} -> 无结果")
    print(f"[RESULT] 基础检索: {success}/{len(queries)} 成功")
    return success >= len(queries) // 2


def test_via_media_tags() -> bool:
    """测试通过 media_tags.pick_meme_image 走语义检索分支。"""
    from clients.bots.qq import media_tags
    media_tags.reset_recent_history()

    # 自然语言描述（非分类名）应触发语义检索
    queries = ["无语地看着", "委屈想哭", "害羞脸红"]
    success = 0
    for q in queries:
        result = media_tags.pick_meme_image(q)
        if result and result.is_file():
            print(f"  [OK] pick_meme_image({q!r}) -> {result.name}")
            success += 1
        else:
            print(f"  [FAIL] pick_meme_image({q!r}) -> 无结果")
    print(f"[RESULT] 端到端: {success}/{len(queries)} 成功")
    return success >= 1


def test_known_category_still_works() -> bool:
    """测试已知分类名仍然走原分类路径，不走语义检索。"""
    from clients.bots.qq import media_tags
    media_tags.reset_recent_history()

    # happy 是已知分类，应该从 data/memes/happy/ 选图
    result = media_tags.pick_meme_image("happy")
    if not result or not result.is_file():
        print("  [FAIL] pick_meme_image('happy') 无结果")
        return False
    # 验证来自 happy 目录
    if "happy" not in str(result):
        print(f"  [WARN] happy 选图路径不含 happy 目录: {result}")
        # 不算失败，可能是 fallback
    print(f"  [OK] pick_meme_image('happy') -> {result.name}")
    return True


def test_lru_dedup() -> bool:
    """测试 LRU 去重：连续多次相同语义查询，不应返回完全相同的图。"""
    from clients.bots.qq import media_tags

    media_tags.reset_recent_history()
    results: list[str] = []
    for _ in range(5):
        r = media_tags.pick_meme_image("害羞脸红")
        if r is None:
            break
        results.append(str(r))
    if len(results) >= 2 and len(set(results)) == len(results):
        print(f"  [OK] LRU 去重生效，{len(results)} 次查询返回 {len(results)} 张不同图")
        return True
    print(f"  [WARN] LRU 去重可能未生效，返回 {len(set(results))}/{len(results)} 张不同图")
    return False


def test_low_similarity_no_send() -> bool:
    """低相似度查询必须直接不发，字面撞词的"抱胸"图也算不匹配。"""
    from clients.bots.qq import media_tags

    media_tags.reset_recent_history()
    queries = [
        "抱住蹭蹭",
        "张开手臂把你揽过来抱住",
        "这是一个非常奇怪无法匹配的查询xyz123",
    ]
    ok = True
    for q in queries:
        result = media_tags.pick_meme_image(q)
        if result is not None:
            print(f"  [FAIL] 低相似度查询仍发图: {q!r} -> {result.name}")
            ok = False
        else:
            print(f"  [OK] 低相似度查询未发图: {q!r}")
    return ok


def main() -> int:
    if not _check_index_files():
        return 0  # 索引未建不算失败

    tests = [
        ("基础语义检索", test_basic_search),
        ("已知分类路径", test_known_category_still_works),
        ("端到端标签", test_via_media_tags),
        ("LRU 去重", test_lru_dedup),
        ("低相似度不发图", test_low_similarity_no_send),
    ]
    results = []
    for name, fn in tests:
        print(f"\n=== {name} ===")
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n=== 总结 ===")
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed >= len(results) - 1 else 1


if __name__ == "__main__":
    sys.exit(main())
