#include "biological_system.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <ctime>

namespace ai_scheduler {

namespace {
constexpr double kPersistIntervalSeconds = 30.0;
constexpr double kOfflineCompensationCapSeconds = 12.0 * 3600.0;
constexpr double kOfflineStepSeconds = 300.0;
} // namespace

BiologicalSystem::BiologicalSystem() 
    : energy_(1.0f), sleep_debt_(0.0f), phase_(CircadianPhase::ACTIVE) {
    lastUpdate_ = std::chrono::system_clock::now();
    lastPersist_ = lastUpdate_;
}

BiologicalSystem::~BiologicalSystem() {
    std::lock_guard<std::mutex> lock(mutex_);
    persistIfDue(true);
}

void BiologicalSystem::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);

    lastUpdate_ = std::chrono::system_clock::now();
    lastPersist_ = lastUpdate_;
    neurotransmitters_.dopamine = config_.baseline_dopamine;
    neurotransmitters_.serotonin = config_.baseline_serotonin;
    neurotransmitters_.norepinephrine = config_.baseline_norepinephrine;
    neurotransmitters_.oxytocin = config_.baseline_oxytocin;
    neurotransmitters_.cortisol = config_.baseline_cortisol;
    energy_ = 1.0f;
    sleep_debt_ = 0.0f;

    updateCircadianRhythm();
    restoreFromStore();
    persistIfDue(true);
}

void BiologicalSystem::update(float deltaTimeSeconds) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    decayNeurotransmitters(deltaTimeSeconds);
    updateCircadianRhythm();
    
    // Natural energy decay if awake
    if (phase_ != CircadianPhase::SLEEP) {
        energy_ -= config_.energy_awake_decay * deltaTimeSeconds;
        sleep_debt_ += config_.sleep_debt_awake_gain * deltaTimeSeconds;
    } else {
        energy_ += config_.energy_sleep_recover * deltaTimeSeconds;
        sleep_debt_ -= config_.sleep_debt_sleep_recover * deltaTimeSeconds;
    }
    
    energy_ = std::clamp(energy_, 0.0f, 1.0f);
    sleep_debt_ = std::clamp(sleep_debt_, 0.0f, 1.0f);

    lastUpdate_ = std::chrono::system_clock::now();
    persistIfDue(false);
}

void BiologicalSystem::restoreFromStore() {
    BiologicalStateSnapshot snapshot;
    if (!store_.load(snapshot)) {
        return;
    }

    neurotransmitters_.dopamine = std::clamp(snapshot.dopamine, 0.0f, 1.0f);
    neurotransmitters_.serotonin = std::clamp(snapshot.serotonin, 0.0f, 1.0f);
    neurotransmitters_.norepinephrine = std::clamp(snapshot.norepinephrine, 0.0f, 1.0f);
    neurotransmitters_.oxytocin = std::clamp(snapshot.oxytocin, 0.0f, 1.0f);
    neurotransmitters_.cortisol = std::clamp(snapshot.cortisol, 0.0f, 1.0f);
    energy_ = std::clamp(snapshot.energy, 0.0f, 1.0f);
    sleep_debt_ = std::clamp(snapshot.sleep_debt, 0.0f, 1.0f);

    const auto saved_at = std::chrono::system_clock::time_point(std::chrono::seconds(snapshot.saved_at_unix));
    const auto now = std::chrono::system_clock::now();
    const double offline_seconds = std::chrono::duration<double>(now - saved_at).count();

    // 进程没运行的那段时间不让生理状态凭空冻结：按 5 分钟为步长补算，
    // 上限 12 小时；同时限制单次恢复的总偏移，避免关机一整天后
    // 一开机就是 energy=0 / sleep_debt=1（认知延迟会被推到上限）。
    constexpr float kMaxOfflineDrift = 0.3f;
    const float energy_before = energy_;
    const float sleep_debt_before = sleep_debt_;
    if (offline_seconds > 0.0) {
        simulateElapsed(offline_seconds, saved_at);
        energy_ = std::clamp(energy_,
            std::max(0.0f, energy_before - kMaxOfflineDrift),
            std::min(1.0f, energy_before + kMaxOfflineDrift));
        sleep_debt_ = std::clamp(sleep_debt_,
            std::max(0.0f, sleep_debt_before - kMaxOfflineDrift),
            std::min(1.0f, sleep_debt_before + kMaxOfflineDrift));
    }

    std::cout << "BiologicalSystem: restored state from " << store_.path()
              << " (offline " << static_cast<long long>(offline_seconds) << "s)" << std::endl;
}

void BiologicalSystem::simulateElapsed(double seconds, std::chrono::system_clock::time_point start) {
    const double capped = std::min(seconds, kOfflineCompensationCapSeconds);
    for (double elapsed = 0.0; elapsed < capped; elapsed += kOfflineStepSeconds) {
        const double step = std::min(kOfflineStepSeconds, capped - elapsed);
        updateCircadianRhythm(start + std::chrono::milliseconds(
            static_cast<long long>((elapsed + step) * 1000.0)));

        decayNeurotransmitters(static_cast<float>(step));
        if (phase_ != CircadianPhase::SLEEP) {
            energy_ -= config_.energy_awake_decay * static_cast<float>(step);
            sleep_debt_ += config_.sleep_debt_awake_gain * static_cast<float>(step);
        } else {
            energy_ += config_.energy_sleep_recover * static_cast<float>(step);
            sleep_debt_ -= config_.sleep_debt_sleep_recover * static_cast<float>(step);
        }
        energy_ = std::clamp(energy_, 0.0f, 1.0f);
        sleep_debt_ = std::clamp(sleep_debt_, 0.0f, 1.0f);
    }
}

void BiologicalSystem::persistIfDue(bool force) {
    if (!store_.enabled()) {
        return;
    }

    const auto now = std::chrono::system_clock::now();
    if (!force && std::chrono::duration<double>(now - lastPersist_).count() < kPersistIntervalSeconds) {
        return;
    }

    BiologicalStateSnapshot snapshot;
    snapshot.dopamine = neurotransmitters_.dopamine;
    snapshot.serotonin = neurotransmitters_.serotonin;
    snapshot.norepinephrine = neurotransmitters_.norepinephrine;
    snapshot.oxytocin = neurotransmitters_.oxytocin;
    snapshot.cortisol = neurotransmitters_.cortisol;
    snapshot.energy = energy_;
    snapshot.sleep_debt = sleep_debt_;
    snapshot.saved_at_unix = std::chrono::duration_cast<std::chrono::seconds>(
        now.time_since_epoch()).count();

    if (store_.save(snapshot)) {
        lastPersist_ = now;
    }
}

void BiologicalSystem::decayNeurotransmitters(float deltaTime) {
    auto decay_to = [this, deltaTime](float& val, float baseline) {
        float diff = baseline - val;
        val += diff * config_.decay_rate * deltaTime;
        val = std::clamp(val, 0.0f, 1.0f);
    };

    decay_to(neurotransmitters_.dopamine, config_.baseline_dopamine);
    decay_to(neurotransmitters_.serotonin, config_.baseline_serotonin);
    decay_to(neurotransmitters_.norepinephrine, config_.baseline_norepinephrine);
    decay_to(neurotransmitters_.oxytocin, config_.baseline_oxytocin);
    decay_to(neurotransmitters_.cortisol, config_.baseline_cortisol);
}

void BiologicalSystem::updateCircadianRhythm() {
    updateCircadianRhythm(std::chrono::system_clock::now());
}

void BiologicalSystem::updateCircadianRhythm(std::chrono::system_clock::time_point now) {
    // std::localtime 返回共享缓冲区，这里用一把局部互斥锁把它变成线程安全调用。
    // 不直接使用 localtime_s/localtime_r：MSVC 的 localtime_s 与 MinGW(C11) 的参数顺序相反。
    static std::mutex time_mutex;
    const time_t t = std::chrono::system_clock::to_time_t(now);
    struct tm local_tm {};
    {
        std::lock_guard<std::mutex> lock(time_mutex);
        const struct tm* shared = std::localtime(&t);
        if (shared != nullptr) {
            local_tm = *shared;
        }
    }
    const int hour = local_tm.tm_hour;
    
    if (hour >= 7 && hour < 9) phase_ = CircadianPhase::WAKE;
    else if (hour >= 9 && hour < 21) phase_ = CircadianPhase::ACTIVE;
    else if (hour >= 21 && hour < 23) phase_ = CircadianPhase::TIRED;
    else phase_ = CircadianPhase::SLEEP;
}

Neurotransmitter BiologicalSystem::getNeurotransmitters() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return neurotransmitters_;
}

void BiologicalSystem::adjustNeurotransmitter(const std::string& name, float delta) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    if (name == "dopamine") neurotransmitters_.dopamine += delta;
    else if (name == "serotonin") neurotransmitters_.serotonin += delta;
    else if (name == "norepinephrine") neurotransmitters_.norepinephrine += delta;
    else if (name == "oxytocin") neurotransmitters_.oxytocin += delta;
    else if (name == "cortisol") neurotransmitters_.cortisol += delta;
    
    // Clamp
    auto clamp = [](float& val) { val = std::clamp(val, 0.0f, 1.0f); };
    clamp(neurotransmitters_.dopamine);
    clamp(neurotransmitters_.serotonin);
    clamp(neurotransmitters_.norepinephrine);
    clamp(neurotransmitters_.oxytocin);
    clamp(neurotransmitters_.cortisol);
}

float BiologicalSystem::getEnergy() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return energy_;
}

void BiologicalSystem::consumeEnergy(float amount) {
    std::lock_guard<std::mutex> lock(mutex_);
    energy_ -= amount;
    energy_ = std::clamp(energy_, 0.0f, 1.0f);
}

void BiologicalSystem::recoverEnergy(float amount) {
    std::lock_guard<std::mutex> lock(mutex_);
    energy_ += amount;
    energy_ = std::clamp(energy_, 0.0f, 1.0f);
}

float BiologicalSystem::getSleepDebt() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return sleep_debt_;
}

CircadianPhase BiologicalSystem::getCircadianPhase() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return phase_;
}

float BiologicalSystem::calculateCognitiveDelay(float complexity) const {
    std::lock_guard<std::mutex> lock(mutex_);
    
    float baseDelay = config_.cognitive_base_delay;
    
    // Energy impact: Low energy -> higher delay
    float energyFactor = 1.0f + (1.0f - energy_) * config_.cognitive_energy_scale;
    
    // Neurotransmitter impact
    // High dopamine -> faster (lower delay)
    // Low serotonin -> slower (hesitation)
    float dopamineFactor = 1.0f - (neurotransmitters_.dopamine - config_.baseline_dopamine) * config_.cognitive_dopamine_scale;
    float serotoninFactor = 1.0f - (neurotransmitters_.serotonin - config_.baseline_serotonin) * config_.cognitive_serotonin_scale;
    float cortisolFactor = 1.0f + (neurotransmitters_.cortisol - config_.baseline_cortisol) * config_.cognitive_cortisol_scale;
    float sleepDebtFactor = 1.0f + sleep_debt_ * config_.cognitive_sleep_debt_scale;
    
    // Complexity scaling
    float complexityDelay = complexity * config_.cognitive_complexity_scale;
    
    float totalDelay = (baseDelay + complexityDelay) * energyFactor * dopamineFactor * serotoninFactor * cortisolFactor * sleepDebtFactor;
    
    return std::max(0.1f, totalDelay);
}

BiologicalConfig BiologicalSystem::getConfig() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return config_;
}

void BiologicalSystem::setConfig(const BiologicalConfig& config) {
    std::lock_guard<std::mutex> lock(mutex_);
    config_ = config;
}

} // namespace ai_scheduler
