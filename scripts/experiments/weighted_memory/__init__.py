"""weighted memory v3 离线实验（C6/C7）。

默认 provider = MiniMax M Plan（``MINIMAX_PLAN_API_KEY`` + ``MiniMax-M3.1-Flash``）；
可用 ``--provider deepseek`` 切换，但两者结果不可直接混算（缓存键含 provider/model）。

    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c6.py --dry-run
    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c6.py
    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c7.py

产物写在 ``output/evaluation/``（不入库）：
- ``c6_extraction_artifacts.json``：三臂提取结果与指标
- ``c7_retrieval_e2e.json``：检索、回答、分支消融
- ``c6_c7_report.md``：可读报告与预注册决策
"""
