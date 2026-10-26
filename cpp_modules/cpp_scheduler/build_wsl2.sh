#!/bin/bash
set -euo pipefail

# 路径全部从脚本位置推导，不再写死仓库绝对路径（旧版写的是 xiaoyou-core）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

# 解释器优先用仓库内 venv_cpu，可用 XIAOYOU_PY 覆盖
PYTHON_EXE="${XIAOYOU_PY:-${PROJECT_ROOT}/venv_cpu/bin/python}"
if [ ! -x "${PYTHON_EXE}" ]; then
    echo "未找到 Python: ${PYTHON_EXE}（可用 XIAOYOU_PY 指定）"
    exit 1
fi

# 有 CUDA Toolkit 时才追加其路径（纯 CPU 构建跳过）
if [ -d /usr/local/cuda ]; then
    export PATH="/usr/local/cuda/bin:${PATH}"
    export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"
fi

echo "=== 主程序 C++ Scheduler Build ==="
echo "Python: $("${PYTHON_EXE}" --version) at ${PYTHON_EXE}"
echo "CUDA: $(nvcc --version 2>/dev/null | grep release || echo 'not found')"
echo "cmake: $(cmake --version | head -1)"
echo ""

# 清理旧 build
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "=== Running CMake ==="
cmake "${SCRIPT_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython_EXECUTABLE="${PYTHON_EXE}" \
    -DPYTHON_EXECUTABLE="${PYTHON_EXE}"

echo ""
echo "=== Building ==="
cmake --build . -j"$(nproc)"

echo ""
echo "=== Build Complete ==="
ls -la scheduler_py*.so 2>/dev/null || echo "WARNING: scheduler_py not found"
