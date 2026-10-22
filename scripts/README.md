# scripts 目录说明

## 目录约定

- `scripts/doc_records/`
  - 正式维护脚本
  - 负责维护 `docs/updates/` 更新日志（按日期一天一个文件）与 `Question_Reviewer/` 分类文件夹
  - 包含：
    - `update_project_records.py`：按日期把 updates 记录写入 `docs/updates/YYYY/MM/YYYY-MM-DD.md`，并按类别追加 Question_Reviewer 记录（自动化场景使用，如模型注册 `--record`）
    - `split_updates_to_daily.py`：一次性把根 `UPDATES.md` 拆到 `docs/updates/`；`--index` 重建索引与根入口，`--check` 校验日期文件结构
    - `split_question_reviewer.py`：一次性拆分脚本，把旧 `Question_Reviewer.md` 按类别拆到 `Question_Reviewer/` 文件夹
    - `question_categories.py`：分类定义（类别文件名、显示名、关键词），新增/调整类别改这里
- `scripts/qq/`
  - QQ 侧数据维护脚本
  - 负责修复或清理 QQ 会话相关的历史数据
- `scripts/git/`
  - Git 提交前检查脚本
  - 负责调用 `gitleaks` 扫描暂存区敏感信息
- `scripts/model_registry/`
  - 云端模型注册脚本
  - `register_cloud_model.py`：交互式接入新模型（选 provider → 在线搜/手填模型 → 自动写入全部注册点）
  - 注册点：`config/settings_model.py` 的 `PROVIDER_DEFAULT_MODELS`、`core/llm/model_capabilities.py` 的
    `VISION_MODEL_KEYWORDS`、视觉路由与 OpenRouter 连通性验证脚本，可选改 `model_routing.yaml` 的默认模型
  - 验证脚本：见 `tests/scripts/model_registry/verify_register_cloud_model.py`
- `scripts/daily/`
  - 日常操作统一入口（薄壳转发，**不含任何业务逻辑**）
  - `daily.py`：`status` / `log` / `index` / `check` / `commit` / `deploy` / `backup` 七个子命令，
    分别转发到 `git status`、`update_project_records.py`、`split_updates_to_daily.py`、
    三项检查脚本（规则一致性 / 行数分档 / 测试审计）、`auto_commit_push.py`、
    `scripts/deploy/deploy_linux.sh`、`scripts/backup/auto_backup.py`
  - 原脚本一律留在原位，本目录只提供短入口；新增常用操作时在 `daily.py` 加一个子命令，不要复制实现
  - 解释器优先取虚拟环境（Windows `venv_cpu/Scripts/python.exe`、Linux `venv_linux/bin/python`），可用 `XIAOYOU_PY` 覆盖
- `scripts/deploy/`
  - Linux 服务器部署脚本（把「代码到位」变成「服务生效」）
  - `deploy_linux.sh`：按 `BASE_SHA..HEAD_SHA` 的变更范围决定装依赖 / 可选编 C++ 与前端 / 重启服务 / 健康检查，
    由 `.github/workflows/deploy-linux.yml` 的 deploy job 调用，也可在服务器上手动执行
  - 配置项全部走环境变量（`REPO_DIR` / `VENV_DIR` / `SERVICE_NAME` / `HEALTH_URL` / `BUILD_CPP` / `BUILD_WEB` 等）
  - 默认 `BUILD_CPP=0`、`BUILD_WEB=0`；重启环节找不到 systemd 单元会主动报错退出，不静默跳过
- `scripts/backup/`
  - 运行时数据按月快照备份（面向 git 之外、丢了不可再生的数据）
  - `auto_backup.py`：把 `companion_data` / `output` / `data` / 学习库 / 隐私配置收进仓库外的备份根，
    同一月份重复运行是增量刷新（size + mtime 相同即跳过），只保留最近 N 个 `YYYY-MM` 快照目录
  - 默认 dry-run、`--apply` 才落盘；备份根用 `--dest`（或 `XIAOYOU_BACKUP_ROOT`）、学习库用 `--study-root` 指定
  - 建议在程序停止时运行；恢复 = 把快照目录里的数据目录拷回原位置，无合并逻辑
- `scripts/tools/`
  - 通用维护 / 一次性脚本统一存放：内存分析与优化、训练数据生成、数据迁移、日记与计划重生成、C++ 构建、角色数据校验等
  - 与按业务线划分的子目录（`import/` `git/` `sync/` `publish/` 等）区分：这里放「手动跑一次」的工具，
    调用方式统一为 `python scripts/tools/<脚本名>.py`
  - 脚本内的项目根一律写 `Path(__file__).resolve().parents[2]`（迁移前是 `parent.parent`，多一层会指到仓库外）
- `scripts/`
  - 只保留 `README.md`；通用维护脚本放 `scripts/tools/`，带业务线的放对应子目录，不再直接堆在根目录

## 当前约束

- 新增“项目维护类脚本”放 `scripts/tools/`，带业务线的放对应语义子目录，不要继续直接堆在 `scripts` 根目录
- 常用操作统一走 `scripts/daily/daily.py` 薄壳入口，不要每次重新拼长命令；
  入口只做转发，业务逻辑仍在原脚本里，禁止在 `daily.py` 里复制实现
- 接入新云端模型一律走 `scripts/model_registry/register_cloud_model.py`，不要手改注册点；
  手改容易漏掉多模态名单或验证脚本，出现“能选但发图走 VL 中转”的半成品注册
- 更新日志按日期归档：新记录直接写 `docs/updates/YYYY/MM/YYYY-MM-DD.md`（不存在则创建），不要回头改历史日期文件；根 `UPDATES.md` 只是入口，索引 `docs/updates/README.md` 由 `split_updates_to_daily.py --index` 重建
- `Question_Reviewer/` 的更新统一走 `scripts/doc_records/update_project_records.py`，不要再手工新建/编辑里面的 `.md` 文件
- 分类定义统一在 `scripts/doc_records/question_categories.py` 维护，不要在其他脚本里重复定义
- 验证脚本放在 `tests/scripts/`，不要把正式工具和验证脚本混在一起

## 文档记录脚本

示例命令：

```powershell
venv_core\Scripts\python.exe scripts\doc_records\update_project_records.py `
  --payload-file scripts\doc_records\payload_update_doc_rules.json `
  --project-root D:\projects\xiaoyou
```

`question_reviewers` 数组里的 entry 可选 `category` 字段（如 `01_active_care`）指定分类文件名，缺省时按标题关键词自动归类。

日常写更新日志不需要 payload：直接编辑当天的 `docs/updates/YYYY/MM/YYYY-MM-DD.md`（不存在就按现有格式新建），写完跑一次
`venv_core\Scripts\python.exe scripts\doc_records\split_updates_to_daily.py --index` 刷新索引与根入口即可。

