#pragma once

#include <cstdint>
#include <mutex>
#include <string>

namespace ai_scheduler {

/// 生物系统状态快照：用于跨进程重启恢复。
/// 字段全部为 0-1 归一化值，saved_at_unix 为 UTC 秒。
struct BiologicalStateSnapshot {
    float dopamine = 0.5f;
    float serotonin = 0.5f;
    float norepinephrine = 0.5f;
    float oxytocin = 0.5f;
    float cortisol = 0.3f;
    float energy = 1.0f;
    float sleep_debt = 0.0f;
    int64_t saved_at_unix = 0;
};

/// 生物状态落盘。
///
/// 只做普通文件读写（不依赖 NVRAM 硬件或 Windows 文件映射），
/// 因此 Windows / Linux 行为一致：
/// - 路径优先级：显式传入 > 环境变量 XIAOYOU_BIO_STATE_PATH > data/bio_state.txt
/// - 环境变量 XIAOYOU_BIO_STATE_DISABLE=1 时整体关闭，全部接口退化为 no-op
/// - 任何 IO 异常都静默失败，绝不影响调度主链路
/// - 写入走 "临时文件 + rename"，避免进程崩溃时留下半截文件
class BioStateStore {
public:
    BioStateStore();
    explicit BioStateStore(std::string path);

    void setPath(std::string path);
    const std::string& path() const { return path_; }
    bool enabled() const { return enabled_; }

    /// 读取快照；文件缺失、损坏、版本不符均返回 false，且不改动 out。
    bool load(BiologicalStateSnapshot& out) const;

    /// 原子写入快照；失败返回 false。
    bool save(const BiologicalStateSnapshot& snapshot);

private:
    static std::string resolvePath();
    static bool readsDisabled();

    std::string path_;
    bool enabled_ = true;
    mutable std::mutex mutex_;
};

} // namespace ai_scheduler
