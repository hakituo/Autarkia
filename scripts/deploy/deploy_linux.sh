#!/usr/bin/env bash
# 小友 Core —— Linux 服务器部署脚本
#
# 职责：把已经同步到本机的代码，变成"真正在跑的新版本"。
# sync 只搬代码；本脚本负责 装依赖 / 编 C++ / 编前端 / 重启服务 / 自检。
#
# 用法（通常由 .github/workflows/deploy-linux.yml 的 deploy job 调用）：
#   BASE_SHA=<旧提交> HEAD_SHA=<新提交> bash scripts/deploy/deploy_linux.sh
#
# 手动执行时可以不传 SHA：此时所有"有变化才做"的判断退化为"总是做"。
#
# 可覆盖的环境变量：
#   REPO_DIR       仓库路径          默认 /home/user/Autarkia
#   VENV_DIR       虚拟环境路径       默认 $REPO_DIR/venv_linux
#   PY             python 解释器      默认 $VENV_DIR/bin/python
#   SERVICE_NAME   systemd 单元名     默认 xiaoyou-core
#   HEALTH_URL     健康检查地址       默认 http://127.0.0.1:8000/api/v1/health
#   HEALTH_TIMEOUT 健康检查超时(秒)    默认 90
#   INSTALL_DEPS   1/0 是否装依赖     默认 1
#   BUILD_CPP      1/0 是否编 C++     默认 0（当前 C++ 调度器基本不用）
#   BUILD_WEB      1/0 是否编前端     默认 0（默认前后端分离，Web 独立跑 3000）
#   RESTART        1/0 是否重启服务   默认 1
#
# 退出码：0 成功；非 0 表示部署中断，CI 会变红，需要人工介入。
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/user/Autarkia}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/venv_linux}"
PY="${PY:-$VENV_DIR/bin/python}"
SERVICE_NAME="${SERVICE_NAME:-xiaoyou-core}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/v1/health}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"

INSTALL_DEPS="${INSTALL_DEPS:-1}"
BUILD_CPP="${BUILD_CPP:-0}"
BUILD_WEB="${BUILD_WEB:-0}"
RESTART="${RESTART:-1}"

BASE_SHA="${BASE_SHA:-}"
HEAD_SHA="${HEAD_SHA:-${BASE_SHA}}"

log() { printf '\n[deploy] %s\n' "$*"; }

if [ ! -d "$REPO_DIR" ]; then
    log "错误：仓库目录不存在 $REPO_DIR"
    exit 1
fi
cd "$REPO_DIR"

# 判断某个路径前缀下是否有改动。
# BASE_SHA 缺失（手动执行）时保守返回"有改动"，宁可多做一次也不漏。
touched() {
    local prefix="$1"
    if [ -z "$BASE_SHA" ]; then
        return 0
    fi
    ! git diff --quiet "$BASE_SHA" "$HEAD_SHA" -- "$prefix"
}

log "部署开始：${BASE_SHA:-<未指定>} -> ${HEAD_SHA:-<未指定>}"
log "当前 HEAD：$(git rev-parse --short HEAD)"

# ── 1. Python 依赖 ───────────────────────────────────────────────
if [ "$INSTALL_DEPS" = "1" ]; then
    if touched pyproject.toml || touched requirements/ || touched uv.lock; then
        log "依赖声明有变化，同步 Python 依赖"
        if [ ! -x "$PY" ]; then
            log "错误：找不到虚拟环境解释器 $PY"
            log "请先创建虚拟环境，或用 VENV_DIR=... 覆盖路径"
            exit 1
        fi
        if command -v uv >/dev/null 2>&1 && [ -f uv.lock ]; then
            log "使用 uv sync --frozen"
            uv sync --frozen
        else
            # requirements/README.md 明确要求：base.txt 与 cpu.txt 必须分成两条命令，
            # 因为后者带独立的 PyTorch --index-url。
            log "使用 pip（base.txt + cpu.txt 分两步）"
            "$PY" -m pip install -r requirements/base.txt
            "$PY" -m pip install -r requirements/cpu.txt
        fi
    else
        log "依赖声明无变化，跳过依赖安装"
    fi
else
    log "INSTALL_DEPS=0，跳过依赖安装"
fi

# ── 2. C++ 调度器（默认关闭）──────────────────────────────────────
if [ "$BUILD_CPP" = "1" ]; then
    if touched cpp_modules/; then
        log "C++ 源码有变化，重新编译调度器"
        # 增量编译：不 rm -rf build，避免每次全量重编（llama.cpp 很慢）。
        # CUDA 显式关闭；-march=native 必须在本机编译，不可跨机搬运产物。
        cmake -S cpp_modules/cpp_scheduler -B cpp_modules/cpp_scheduler/build \
            -DCMAKE_BUILD_TYPE=Release \
            -DLLAMA_CUDA=OFF \
            -DGGML_CUDA=OFF \
            -DPython_EXECUTABLE="$PY" \
            -DPYTHON_EXECUTABLE="$PY"
        cmake --build cpp_modules/cpp_scheduler/build -j"$(nproc)"
    else
        log "C++ 源码无变化，跳过编译"
    fi
else
    log "BUILD_CPP=0，跳过 C++ 编译"
fi

# ── 3. Web 前端（默认关闭）───────────────────────────────────────
# 默认 serve_frontend=false，8000 是纯后端，Web 独立跑 3000。
# 只有当你在服务器上自己托管前端时，才需要 BUILD_WEB=1。
if [ "$BUILD_WEB" = "1" ]; then
    if touched clients/frontend/aveline-web/; then
        log "前端有变化，构建 dist"
        (
            cd clients/frontend/aveline-web
            npm ci --no-audit --no-fund
            npm run build
        )
    else
        log "前端无变化，跳过构建"
    fi
else
    log "BUILD_WEB=0，跳过前端构建"
fi

# ── 4. 重启服务 ─────────────────────────────────────────────────
if [ "$RESTART" = "1" ]; then
    log "重启服务 $SERVICE_NAME"
    if ! systemctl cat "${SERVICE_NAME}.service" >/dev/null 2>&1; then
        log "错误：未找到 systemd 单元 ${SERVICE_NAME}.service"
        log "请按实际的重启方式改造本段（pm2 / supervisorctl / 自建脚本），"
        log "或用 SERVICE_NAME=... 指定正确的单元名。"
        log "这里刻意报错而不是静默跳过：一次'看起来成功'的部署比失败更危险。"
        exit 1
    fi
    sudo systemctl restart "$SERVICE_NAME"
    log "已下发重启指令"
else
    log "RESTART=0，跳过重启"
fi

# ── 5. 健康检查 ─────────────────────────────────────────────────
log "健康检查 $HEALTH_URL（最长 ${HEALTH_TIMEOUT}s）"
deadline=$((SECONDS + HEALTH_TIMEOUT))
until curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        log "错误：健康检查超时，服务可能未正常启动"
        log "排查建议：sudo journalctl -u ${SERVICE_NAME} -n 100 --no-pager"
        exit 1
    fi
    sleep 3
done

log "部署完成，服务健康"
