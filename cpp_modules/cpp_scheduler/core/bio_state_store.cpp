#include "bio_state_store.h"

#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <system_error>

namespace ai_scheduler {
namespace {

constexpr const char* kVersionKey = "version";
constexpr int kFormatVersion = 1;

std::string trim(const std::string& value) {
    const auto begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) {
        return std::string();
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

bool parseFloat(const std::string& text, float& out) {
    try {
        const float parsed = std::stof(text);
        if (!std::isfinite(parsed)) {
            return false;
        }
        out = parsed;
        return true;
    } catch (...) {
        return false;
    }
}

} // namespace

std::string BioStateStore::resolvePath() {
    const char* from_env = std::getenv("XIAOYOU_BIO_STATE_PATH");
    if (from_env != nullptr && *from_env != '\0') {
        return std::string(from_env);
    }
    return std::string("data/bio_state.txt");
}

bool BioStateStore::readsDisabled() {
    const char* flag = std::getenv("XIAOYOU_BIO_STATE_DISABLE");
    if (flag == nullptr) {
        return false;
    }
    const std::string value = trim(flag);
    return value == "1" || value == "true" || value == "TRUE" || value == "on";
}

BioStateStore::BioStateStore()
    : path_(resolvePath()), enabled_(!readsDisabled()) {}

BioStateStore::BioStateStore(std::string path)
    : path_(std::move(path)), enabled_(!readsDisabled()) {}

void BioStateStore::setPath(std::string path) {
    std::lock_guard<std::mutex> lock(mutex_);
    path_ = std::move(path);
}

bool BioStateStore::load(BiologicalStateSnapshot& out) const {
    if (!enabled_) {
        return false;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    try {
        std::ifstream in(path_, std::ios::binary);
        if (!in.is_open()) {
            return false;
        }

        BiologicalStateSnapshot snapshot;
        int version = 0;
        std::string line;
        while (std::getline(in, line)) {
            const auto sep = line.find('=');
            if (sep == std::string::npos) {
                continue;
            }
            const std::string key = trim(line.substr(0, sep));
            const std::string value = trim(line.substr(sep + 1));
            if (key == kVersionKey) {
                try {
                    version = std::stoi(value);
                } catch (...) {
                    return false;
                }
                continue;
            }
            if (key == "saved_at_unix") {
                try {
                    snapshot.saved_at_unix = std::stoll(value);
                } catch (...) {
                    return false;
                }
                continue;
            }

            float parsed = 0.0f;
            if (!parseFloat(value, parsed)) {
                continue;
            }
            if (key == "dopamine") snapshot.dopamine = parsed;
            else if (key == "serotonin") snapshot.serotonin = parsed;
            else if (key == "norepinephrine") snapshot.norepinephrine = parsed;
            else if (key == "oxytocin") snapshot.oxytocin = parsed;
            else if (key == "cortisol") snapshot.cortisol = parsed;
            else if (key == "energy") snapshot.energy = parsed;
            else if (key == "sleep_debt") snapshot.sleep_debt = parsed;
        }

        if (version != kFormatVersion || snapshot.saved_at_unix <= 0) {
            return false;
        }

        out = snapshot;
        return true;
    } catch (...) {
        return false;
    }
}

bool BioStateStore::save(const BiologicalStateSnapshot& snapshot) {
    if (!enabled_) {
        return false;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    try {
        const std::filesystem::path target(path_);
        const std::filesystem::path parent = target.parent_path();
        if (!parent.empty()) {
            std::error_code ec;
            std::filesystem::create_directories(parent, ec);
        }

        std::filesystem::path temp = target;
        temp += ".tmp";

        {
            std::ofstream out(temp, std::ios::binary | std::ios::trunc);
            if (!out.is_open()) {
                return false;
            }
            out << std::setprecision(9);
            out << kVersionKey << '=' << kFormatVersion << '\n';
            out << "saved_at_unix=" << snapshot.saved_at_unix << '\n';
            out << "dopamine=" << snapshot.dopamine << '\n';
            out << "serotonin=" << snapshot.serotonin << '\n';
            out << "norepinephrine=" << snapshot.norepinephrine << '\n';
            out << "oxytocin=" << snapshot.oxytocin << '\n';
            out << "cortisol=" << snapshot.cortisol << '\n';
            out << "energy=" << snapshot.energy << '\n';
            out << "sleep_debt=" << snapshot.sleep_debt << '\n';
            out.flush();
            if (!out.good()) {
                out.close();
                std::error_code ec;
                std::filesystem::remove(temp, ec);
                return false;
            }
        }

        // Windows 上 rename 不能覆盖已存在文件，先删旧文件再改名。
        std::error_code ec;
        std::filesystem::remove(target, ec);
        std::filesystem::rename(temp, target, ec);
        if (ec) {
            std::error_code cleanup;
            std::filesystem::remove(temp, cleanup);
            return false;
        }
        return true;
    } catch (...) {
        return false;
    }
}

} // namespace ai_scheduler
