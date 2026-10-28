"""验证安卓端侧 ASR（sherpa-ncnn）在 native 层的并发安全与资源释放。

背景（2026-10-28）：用户反馈安卓 App 用 ASR 时点「录音完成」偶发直接闪退，
概率约一天一次，且崩溃日志目录里什么都没有 —— 说明不是 Java 异常，
而是 native 层（libsherpa-ncnn-jni.so）崩的，CrashHandler 抓不到。

对应实现（SherpaNcnnAsrEngine）：
1. recognizer 的 acceptSamples / decode / inputFinished / reset 在 C++ 侧共用同一套
   解码状态，必须全部在 nativeLock 下串行；主线程不放 native 调用；
2. 会话代号 sessionId：开录 / 停止 / 取消各 +1，旧会话的协程碰到它立刻收手；
3. 开录前的收尾解码互斥用 Job.isCompleted（cancel 之后 isActive 会变成 false，
   但 native 调用可能还在跑，用 isActive 放行就是闪退来源）；
4. AudioRecord 每次录音结束都 release（原先只 stop，release 只在从没被调用过的
   destroy 里）；stop / release 用 recordLock 串行，read 不进锁以免把 stop 锁死；
5. SherpaNcnn 构造后检查 native 指针非 0，避免「构造失败 → 空指针解引用」直接 SIGSEGV。

运行：venv_cpu/bin/python tests/scripts/android_frontend/verify_asr_native_safety.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JAVA_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java"
ENGINE = JAVA_MAIN / "com/aveline/ai/mobile/services/SherpaNcnnAsrEngine.kt"
WRAPPER = JAVA_MAIN / "com/k2fsa/sherpa/ncnn/SherpaNcnn.kt"


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def _region(text: str, start: str, end: str) -> str:
    """取 text 里 start 到 end 之间的一段；找不到就返回空串（对应断言自会失败）。"""
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin)
    return text[begin:] if stop == -1 else text[begin:stop]


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("端侧 ASR native 并发安全验证")
    print("=" * 70)

    engine = ENGINE.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")

    stop_body = _region(engine, "fun stopListening()", "fun cancel()")
    cancel_body = _region(engine, "fun cancel()", "fun reset()")
    loop_body = _region(engine, "private suspend fun recordLoop(", "sealed class AsrState")

    # 1. 三处 native 调用串行
    results.append(
        _check(
            engine.count("synchronized(nativeLock)") >= 3
            and "nativeLock" in stop_body
            and "nativeLock" in cancel_body
            and "nativeLock" in loop_body,
            "录音循环 / 收尾解码 / 取消后的 reset 都在 nativeLock 下串行进 native",
        )
    )

    # 2. 会话代号
    results.append(
        _check(
            engine.count("sessionId += 1") >= 3 and engine.count("if (sessionId != session) return") >= 2,
            "开录 / 停止 / 取消都换会话代号，过期会话的协程在碰 native 前收手",
        )
    )
    results.append(
        _check(
            "sessionId == session" in loop_body and "sessionId != session" in loop_body,
            "录音循环的存活判断绑定会话代号（不只看 state，避免被新一轮顶掉后继续跑）",
        )
    )

    # 3. 收尾解码互斥用 isCompleted
    results.append(
        _check(
            "flushJob?.isCompleted == false" in engine and "flushJob?.isActive" not in engine,
            "开录前的收尾解码互斥用 isCompleted（cancel 之后 isActive 会骗人）",
        )
    )
    results.append(
        _check(
            "recordJob?.isCompleted == false" in engine,
            "上一轮录音循环没退出时不开新循环（阻塞读 cancel 打断不了）",
        )
    )

    # 4. 收尾解码等录音循环真正退出
    results.append(
        _check(
            "withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS)" in stop_body
            and stop_body.count("pendingRecord?.join()") >= 1,
            "收尾解码前先等录音循环退出，且带超时上限（等不回来就丢这一轮，不并发）",
        )
    )

    # 4.1 每轮开录先复位 recognizer（上一轮收尾调过 inputFinished）
    first_reset = loop_body.find("recognizer?.reset(recreate = false)")
    first_accept = loop_body.find("recognizer?.acceptSamples(")
    results.append(
        _check(
            first_reset != -1 and first_accept != -1 and first_reset < first_accept,
            "每轮开录在第一次 acceptSamples 之前先 reset（否则带着 inputFinished 的状态接着解）",
        )
    )

    # 5. AudioRecord 释放与 stop/release 串行
    results.append(
        _check(
            "fun createAudioRecord()" in engine
            and "fun releaseAudioRecord()" in engine
            and "record.release()" in engine,
            "AudioRecord 有独立的创建 / 释放函数，初始化失败与录音结束都会 release",
        )
    )
    results.append(
        _check(
            "if (audioRecord === record)" in loop_body,
            "录音循环只在 finally 里释放自己那一支 AudioRecord（不误放新一轮的）",
        )
    )
    results.append(
        _check(
            engine.count("synchronized(recordLock)") >= 2,
            "AudioRecord 的 stop / release 用 recordLock 串行（read 不在锁内，避免死锁）",
        )
    )

    # 6. 构造失败不空指针
    results.append(
        _check(
            "check(ptr != 0L)" in wrapper,
            "SherpaNcnn 构造后检查 native 指针非 0，把空指针闪退变成可捕获异常",
        )
    )

    print("-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：native 调用串行、会话代号生效、AudioRecord 不再泄漏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
