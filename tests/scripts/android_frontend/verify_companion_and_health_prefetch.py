"""静态验证「伴侣详情预加载 + 三星健康快照复用 + 详情滑动掉帧」三项优化。

对应诉求：安卓端伴侣详情加载慢、生活页同步三星健康卡几秒、详情页左右滑动掉帧。

这些改动都是运行时行为优化，无法在沙箱里跑 Gradle（见 RULES.md §5），
所以这里按关键结构做静态核对：结构在 = 优化路径在；结构被改回旧实现 = 直接报错。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ANDROID = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)


def read(relative: str) -> str:
    """读取 Android 源文件并统一换行。"""
    return (ANDROID / relative).read_text(encoding="utf-8").replace("\r\n", "\n")


def require(source: str, name: str, *needles: str) -> None:
    """断言源码包含全部关键结构。"""
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise AssertionError(f"{name} 缺少关键实现: {missing}")


def forbid(source: str, name: str, *needles: str) -> None:
    """断言源码不再包含旧实现。"""
    hit = [needle for needle in needles if needle in source]
    if hit:
        raise AssertionError(f"{name} 仍存在旧实现: {hit}")


def check_startup_sync_cache() -> None:
    """启动同步必须把快照留在单例缓存里，Life 页直接复用，不再读第二遍 SDK。"""
    manager = read("services/health/StartupHealthSyncManager.kt")
    require(
        manager,
        "StartupHealthSyncManager.kt",
        "data class SamsungHealthSnapshotCache(",
        "val reported: Boolean = false",
        "val cache: StateFlow<SamsungHealthSnapshotCache?>",
        "suspend fun awaitStartupSync(maxWaitMs: Long)",
        "suspend fun <T> withSamsungLock",
        "val isSyncing: Boolean",
    )
    # 顺序要求：先写缓存再 POST —— 上报失败也不能让 UI 层丢掉这份数据。
    cache_pos = manager.find("_cache.value = SamsungHealthSnapshotCache(snapshot, readAt, reported = false)")
    post_pos = manager.find("healthRepository.syncHealthData(")
    if cache_pos < 0 or post_pos < 0 or cache_pos > post_pos:
        raise AssertionError("syncNow 必须先把快照写入缓存，再上报后端")


def check_life_page_reuse() -> None:
    """Life 页要复用启动同步的结果，而不是自己再读一次全量 SDK。"""
    view_model = read("presentation/health/DailyDataViewModel.kt")
    require(
        view_model,
        "DailyDataViewModel.kt",
        "observeStartupHealthCache()",
        "startupHealthSyncManager.cache.collect",
        "awaitStartupSync(STARTUP_SYNC_WAIT_MS)",
        "startupHealthSyncManager.withSamsungLock",
        "startupHealthSyncManager.markSynced(snapshot)",
        "lastRefreshTime = startupHealthSyncManager.lastSyncAt",
    )

    permissions = read("data/samsung/SamsungHealthPermissions.kt")
    # 已授权时不能进主线程：逐项比对 24 个权限就是"进生活页卡一下"的来源。
    main_pos = permissions.find("withContext(Dispatchers.Main)")
    fast_pos = permissions.find("if (hasPermissions()) return true")
    if fast_pos < 0 or main_pos < 0 or fast_pos > main_pos:
        raise AssertionError("ensurePermissions 必须先走 IO 判定 hasPermissions，再考虑主线程请求")


def check_clock_decoupled() -> None:
    """时钟不能塞在 StatusUiState 里，否则每秒重整整棵常驻面板。"""
    ui_state = read("presentation/status/ui/StatusUiState.kt")
    forbid(ui_state, "StatusUiState.kt", "val clock")

    view_model = read("presentation/status/StatusViewModel.kt")
    require(
        view_model,
        "StatusViewModel.kt",
        "val clock: StateFlow<String>",
        "fun forceRefreshStatus()",
        "fun refreshStatusForPersona(persona: String?, force: Boolean = false)",
    )
    forbid(view_model, "StatusViewModel.kt", "clock = formatted")

    status_tab = read("presentation/companion/CompanionStatusTab.kt")
    require(
        status_tab,
        "CompanionStatusTab.kt",
        "clockFlow: StateFlow<String>",
        "val clock by clockFlow.collectAsStateWithLifecycle()",
    )
    forbid(status_tab, "CompanionStatusTab.kt", "uiState.clock")


def check_panel_prefetch() -> None:
    """聊天页预加载 + 打开面板不再重复请求 + 滑动副作用只挂在稳定页。"""
    chat = read("presentation/chat/ChatScreen.kt")
    require(
        chat,
        "ChatScreen.kt",
        "memoryViewModel.setViewingSession(uiState.currentSession?.id)",
        "memoryViewModel.setViewingPersona(fn)",
        "statusViewModel.setControlContext(fn, uiState.currentSession?.id)",
        "memoryViewModel.ensureLoaded()",
    )
    forbid(chat, "ChatScreen.kt", "statusViewModel.refreshStatus()")

    panel = read("presentation/chat/ChatCompanionPanel.kt")
    require(
        panel,
        "ChatCompanionPanel.kt",
        "statusViewModel.refreshStatusForPersona(viewingFilename)",
        "memoryViewModel.ensureLoaded()",
        "clockFlow = statusViewModel.clock",
    )

    screen = read("presentation/companion/CompanionScreen.kt")
    require(
        screen,
        "CompanionScreen.kt",
        "beyondViewportPageCount = 1",
        "LaunchedEffect(pagerState.settledPage)",
    )
    forbid(screen, "CompanionScreen.kt", "isScrollInProgress")

    memory = read("presentation/memory/MemoryViewModel.kt")
    require(memory, "MemoryViewModel.kt", "fun ensureLoaded()", "initialLoadStarted")
    forbid(memory, "MemoryViewModel.kt", "init {\n        // 初始先用 null 加载一次")

    persona = read("presentation/persona/PersonaViewModel.kt")
    require(persona, "PersonaViewModel.kt", "getPersonasRawCached()")
    forbid(persona, "PersonaViewModel.kt", "personaRepository.getPersonasRaw().getOrThrow()")


def main() -> int:
    print("伴侣详情预加载 / 三星健康快照复用 / 滑动掉帧 静态验证")
    print("=" * 70)
    check_startup_sync_cache()
    print("PASS 启动同步把快照写入单例缓存（先缓存后上报）")
    check_life_page_reuse()
    print("PASS Life 页复用启动同步快照，权限判定不走主线程")
    check_clock_decoupled()
    print("PASS 时钟与 StatusUiState 解耦，只在状态卡片内部订阅")
    check_panel_prefetch()
    print("PASS 聊天页预加载、面板不重复请求、Pager 预组合且无滑动期副作用")
    print("-" * 70)
    print("[OK] 三项性能优化静态结构核对通过（Gradle 编译以 Android Studio 回传为准）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
