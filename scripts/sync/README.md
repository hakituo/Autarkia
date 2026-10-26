# 跨系统共享与学习数据同步

这台机器是 **Windows / Linux 双启动**（Linux 与 G 盘在同一块物理盘上），同一时刻只有一个系统在线，
因此不存在"两台机器互相 SSH"的场景，只有两条路：

1. **共享同一份**（推荐）：把数据放到两个系统都能读写的分区上，两个系统读写同一份文件，不用同步；
2. **切换系统时同步**：两边各留一份，用中转目录（hub）拉平。

下面两节分别对应这两条路，可以只用其中一条，也可以先共享日志、再同步学习数据。

---

## 一、共享根：两个系统读写同一个日志文件夹

新增环境变量 `AUTARKIA_SHARED_ROOT` 指向一个两边都能读写的目录，日志目录与学习数据中转目录
就都落到它下面。**不设这个变量时，所有路径与加这个功能之前完全一致**，可以直接回退。

### 1. 选一个共享位置

要求是 NTFS / exFAT 这类两个系统都能挂载的文件系统。本机可选：

| 位置 | 说明 |
| --- | --- |
| `G:`（669GB NTFS，与 Linux 同一块物理盘） | 推荐，和 Linux 分区同盘，挂载稳定 |
| `E:`（195GB NTFS） | 现在放着 `xiaoyou-models`，也可以放 |
| exFAT U 盘 | 只在插入时可用，不适合长期挂 |

### 2. Windows 侧设置

```powershell
setx AUTARKIA_SHARED_ROOT "G:\Autarkia-shared"
mkdir "G:\Autarkia-shared"
```

`setx` 写入用户环境变量，**新开的**命令行 / 服务才生效；当前窗口可临时补一句
`$env:AUTARKIA_SHARED_ROOT = "G:\Autarkia-shared"`。

### 3. Linux 侧设置

```bash
# 1) 建挂载点并挂载（UUID 用 sudo blkid 查）
#    别写 /dev/nvmeXnYpZ：两块 NVMe 的重启枚举顺序会互换，设备名不保证稳定
sudo mkdir -p /mnt/G
sudo mount -t ntfs-3g /dev/disk/by-uuid/E2BE475FBE472B7D /mnt/G

# 2) 写入 /etc/fstab 开机自动挂载（同样的分区，UUID 本就稳定）
UUID=<分区UUID>  /mnt/G  ntfs-3g  defaults,uid=1000,gid=1000,umask=022  0  0

# 3) 环境变量（对 systemd 服务与登录 shell 都生效）
echo 'AUTARKIA_SHARED_ROOT=/mnt/G/Autarkia-shared' | sudo tee -a /etc/environment
```

### 4. 必须关掉 Windows 快速启动

**Windows 的"快速启动"本质是休眠**：开着它，Linux 挂载 NTFS 时只能只读，写入会全部失败。
关法：控制面板 → 电源选项 → 选择电源按钮的功能 → 更改当前不可用的设置 → 取消"启用快速启动"。
另外不要在 Windows 上休眠后再进 Linux。

### 5. 生效范围

| 数据 | 配置前 | 配置后 |
| --- | --- | --- |
| 日志根（`logs/YYYY/M/D`、模块日志、auto_heal、llm 调用日志、错误收集、memory watchdog 等） | `<项目根>/logs` | `<共享根>/logs` |
| 学习数据中转目录 | 需显式传 `--hub` | `<共享根>/learning_hub` |

日志根由 `core/utils/shared_roots.py` 统一解析（`get_logs_root()`），代码里不再散落
`get_project_root() / "logs"`。**若你在配置里显式配了绝对日志目录，则以配置为准**，不被共享根劫持。

两个系统写同一个日志文件夹时，同一天的同名模块日志是**追加**写入（不会互相截断），
但轮转产生的 `.1` / `.2` 备份可能互相覆盖——日志丢了不影响业务，介意的话可以在共享根下再按系统分层。

---

## 二、学习数据同步脚本

适合"两边各存一份、切换系统时拉平"的场景。

```bash
# 出计划（默认 dry-run，不写任何文件）
python scripts/sync/learning_data_sync.py --hub /mnt/G/Autarkia-sync

# 确认后真正执行
python scripts/sync/learning_data_sync.py --hub /mnt/G/Autarkia-sync --apply
```

配了 `AUTARKIA_SHARED_ROOT` 时 `--hub` 可省略，默认用 `<共享根>/learning_hub`；
也可以继续用环境变量 `AUTARKIA_LEARNING_SYNC_HUB` 单独指定。

### 同步哪些数据（分组）

| 分组 | 内容 | 基准根 |
| --- | --- | --- |
| `vocab` | FSRS 背单词进度 `vocab_progress.json`（按单词并集合并）/ `vocab_meta.json`、每日生词日志（按单词并集合并）、长期生词本 | 项目根 |
| `daily` | 每日计划 / 日记 / 学习摘要、每日画像、每日背单词与测验状态 | 用户数据根 |
| `focus` | 专注会话记录 | 用户数据根 |
| `study_state` | 学习系统状态：学习时长、正确率、知识点掌握度、薄弱点（`.state/`） | 学习库根 |
| `chat` | 聊天历史真源：`companion_data/*/chat_history/` 下的 `*.jsonl` 与当天 `index.json` | 运行时数据根（`companion_data`） |
| `memories` | 记忆：`companion_data/*/memories/` 下的短期 / 加权 / 会话列表 / 指纹索引持久状态 | 运行时数据根（`companion_data`） |
| `life_state` | 角色作息与当日计划：`companion_data/character_daily/*state*.json`（`sleep_states.json` / `daily_state.json`） | 运行时数据根（`companion_data`） |
| `persona` | 月度蒸馏记忆：`core/character/configs/extra/**/distilled_profile.md` | 项目根 |

`--groups vocab,daily` 只同步指定分组。会跳过备份文件（`*.bak` / `*.tmp` / `*.sync-tmp`）、
冲突副本（`*.sync-conflict-*`，它只是本地留档，传播过去只会让两端循环增殖）、`backups/` 目录、
设备使用流水 `app_usage.jsonl`（平台相关且体积大），以及 SQLite 派生库（`*.db` / `*.db-wal` / `*.db-shm`）；
单文件超过 `--max-mb`（默认 16MB）也跳过。

### 判定规则（三向比对）

基线 = 上次同步后双方共同的内容指纹（存在 `companion_data/sync/learning_data_state.json`）。

| 情况 | 动作 |
| --- | --- |
| 一端相对基线有改动 | 从改动的一端同步到另一端 |
| 两端内容一致 | 跳过 |
| 两端都改过（或无基线且都有） | 冲突：取 mtime 更新的一方，另一方另存 `<name>.sync-conflict-<时间戳>` |
| 一端文件消失 | 默认**只报告不删除**；加 `--propagate-delete` 才真的删另一端 |

写文件一律先写 `.sync-tmp` 再原子替换，不会留下半截文件。

### 聊天历史（`chat`）为什么不是「谁新用谁」

聊天记录一个会话一天一个 JSONL，**两个系统都会往同一个文件里追加**，整文件「谁新用谁」
会把另一边的消息直接丢掉。因此 `chat` 分组的清单项带合并策略，两端都相对基线改过时走
**并集合并**（`merge`），而不是冲突覆盖：

| 文件 | 合并规则 |
| --- | --- |
| `*.jsonl` | 按 `event_id` 去重取并集，再按 `(timestamp, 行内容)` 排序（没有 `event_id` 的旧行按整行内容去重） |
| 当天 `index.json` | 把两边的 `files` 数组合并（按 `relative_path` 去重，优先保留带 `readable_title` 的条目）并排序 |

- 合并结果**同时写回双方**，因此两边最终内容一致；下一次比对直接判为「两端内容一致」。
- 合并与先后顺序无关（`union(A,B) == union(B,A)`），对已合并结果再合并一次也不变（幂等）。
- 只有一端相对基线改过时仍走普通复制——不会把另一边已经删掉的内容「复活」。
- 派生数据不参与同步：`companion_data/*/indexes/*.db`（SQLite + WAL）留在各系统本地，
  由 `chat_history_index.ensure_sync` 在下次查询时按 JSONL 真源重建（它本来就是纯派生）。

### 记忆（`memories`）同理：按条目身份取并集

记忆也是两端各自累积的，整文件覆盖会丢掉另一边的积累。合并统一遵循
**按条目身份取并集，同一身份保留「更新」的一份**，三种落盘形状都覆盖：

| 形状 | 例子 | 身份 | 取用规则 |
| --- | --- | --- | --- |
| 顶层数组 | `short_term/*_short.json`、`sessions.json` | 条目 `id`（缺 `id` 时用内容指纹） | 同身份取时间更新的一份 |
| 含条目数组的对象 | `weighted/*/*_weighted.json` 的 `weighted_memories` | 条目 `id` | 列表同上；其余标量键取更新的一方（如 `last_updated` 取更晚的） |
| 「指纹 → 条目」映射 | `persistent_states_*.json` | 顶层键（sha256 指纹） | 同键取 `updated_at` 更新的一份 |

「更新」按条目里 `timestamp` / `last_access_time` / `updated_at` / `created_at` / `last_updated`
的最大值判断（数字与时间串混排不会报错），并列时用规范化内容兜底，因此结果与合并顺序无关、
对已合并结果幂等；数组会按该时间键重排。

> 并集合并的前提同样是「两端都相对基线改过」。只有一端改过时走普通复制，所以**删除仍能正常传播**；
> 只有「两端都改过」的窗口里，某一边单独删掉的条目会被另一边的版本补回来（这是刻意的取舍：
> 宁可能多留一条，也不丢记忆）。

### 角色作息 / 当日计划（`life_state`）：按内嵌时间逐角色取新

`companion_data/character_daily/sleep_states.json`（`{role_id: 作息状态}`）与
`daily_state.json`（`{"date": ..., "plans": {role_id: 当日计划}}`）都是「按角色存一份当前
状态」，两端各写一份，**mtime 完全不可比**——切换系统时刚开机的一端会拿「还没同步过来的
旧状态」重新写一份，mtime 反而更新。

2026-10-16 实测：白天在 Linux 跟角色聊了一整天（角色 07:04 就醒了），Windows 侧仍是
`phase=sleeping`，而 Windows 15:59 启动后把文件重写成 mtime 15:59（比 Linux 的 15:13 还新）。
按 mtime 裁决就会把「还在睡」选走，于是程序刚启动就给用户发「下午好。这下真睡多了，都四点才起」。

因此按状态里**内嵌的时间**判新旧，并且**按角色逐个合并**（同一文件里不同角色可能分别在两端
推进，整文件二选一会回退另一端）：

| 优先 | 字段 | 说明 |
| --- | --- | --- |
| 1 | `date` | `YYYY-MM-DD`，字符串比较即时间顺序 |
| 2 | 子树里最大的 epoch 秒 | 只在 `1e9 ~ 4e9`（2001~2096）区间内认，避免把时长 / 评分误当时间戳 |

形状不认识、或两端形状不一致时退回「整份取更新的」，不做逐角色合并。输出统一用 `\n`：
Windows 侧写出来是 CRLF、Linux 侧是 LF，不统一会让两端指纹永远不一致，每次同步都白跑一次合并。

### 追加型日志（`daily/**/*.jsonl`、`.state/**/*.jsonl`）同样按行并集

`daily/` 与 `Study/.state/` 是整目录递归同步（默认整文件覆盖），但目录里**混着追加型
JSONL**：`device_context.jsonl`（设备状态流水）、`notifications.jsonl`（通知流水）、
`health_data.jsonl`、`active_care_actions.jsonl`、`chat_actions.jsonl`、
`learning_events/*.jsonl`。整文件覆盖会让一边的条目直接消失——2026-10-13 实测因此丢了
**2456 行**，只能从 `.sync-conflict-*` 副本里捞回来。

因此这两处单独挂了 `jsonl_union`（清单里放在递归项之后，用后者覆盖合并策略）。
`union_jsonl` 的时间解析兼容三种写法，否则顺序会乱：

| 写法 | 例子 | 出现在 |
| --- | --- | --- |
| 秒级数字 / 数字字符串 | `1791884285.295` | 聊天记录、通知 |
| 毫秒级数字 / 数字字符串 | `"1790509713297"` | 通知 |
| ISO 8601 字符串 | `2026-09-26T21:51:29.631983Z`、`2026-09-27T05:51:30+08:00` | 设备流水（`server_timestamp` / `last_updated`） |

> 设备流水只有一个 ISO 串的 `server_timestamp`。旧实现只认数字型 `timestamp`，
> 这类记录会全部落到 0、退化成按行内容排序，合并后时间轴全乱——已修。

### 按天派生的复习状态（`_review*_state.json`）：按「派生来源日期」选新

`data/study_data/English/Words/daily/` 下有三个按天从进度派生的状态文件：
`_review_queue_state.json`（当天锁定的复习队列）、`_review_batch_state.json`
（当天批次）、`_review_source_state.json`（最后复习到的来源日期）。

它们两端各写一份、内容必然不同，**mtime 完全不可比**：一端刚开机，就可能拿还没同步
过来的旧进度生成一份全新文件，mtime 反而比另一端更晚。2026-10-16 实测：Linux 用停在
10-03 的进度生成了 365 条队列（mtime 00:45），Windows 用 10-15 的进度生成了 32 条
（mtime 00:17）——按 mtime 裁决会把用旧数据生成的那份选走。

因此这三个文件挂 `dated_state` 策略，按「**派生来源日期**」判新旧：

| 优先 | 字段 | 说明 |
| --- | --- | --- |
| 1 | `source_date` | 派生来源的日期；顶层没有时取 `entries` 里最大的（`YYYY/MM/DD` 字符串比较即时间顺序） |
| 2 | `selected_at` | 同一来源日期时，比选取时刻 |
| 3 | `version` | 兜底 |

任一解析不了就返回 `None`，交回冲突流程按 mtime 处理——不会因格式意外而误判。

> 补充说明：复习队列的**条数**本身有自愈能力——`quiz.py` 每次都按当前进度重算候选，
> 再与锁定队列求交集，所以进度同步过来后条数会自动对齐；队列文件主要决定**顺序**。
> 真正会导致「待复习数不对」的是进度文件没同步过来，靠 `AUTARKIA_SYNC_ON_START=1` 解决。

### 背单词进度与每日生词日志（`vocab`）：按单词取并集

`output/user_data/vocab_progress.json` 是 `{单词: 调度状态}` 的映射。两端在两次同步之间
都可能各自背单词，整文件按 mtime 取胜会丢掉另一端新学的词（2026-10-25 实测：Linux 侧
10-23～10-24 的进度没有一条到达 Windows，新词被重新当成「从未学过」）。因此：

| 文件 | 合并规则 |
| --- | --- |
| `vocab_progress.json` | 按单词取并集；同一单词保留末次复习更晚的一份调度字段（`reps` / `interval` / `fsrs_*`），`history` 按 `(timestamp, quality, source)` 去重后合并 |
| `daily/YYYY/MM/DD.txt` | 每行 `单词[ 次数]`，按单词取并集；同词取较大次数（与 `UnfamiliarWordBook` 的去重口径一致），空占位文件不会覆盖实际记录 |

- 结果统一 `sort_keys`、`\n` 换行，与合并顺序无关、对已合并结果幂等；
- 任一侧解析失败（JSON 损坏 / 非 UTF-8）时返回 `None`、不落盘，保留两端原文件：
  合并结果会同时写回双方，拿能读的一侧去覆盖损坏文件会让可人工抢救的内容直接消失；
- 长期生词本 `unfamiliar_word.txt` 仍按整文件复制——它可能含人工维护的空行分组与注释，
  不在这里重排。

### 月度蒸馏记忆（`persona`）：保留信息量更大的一份

`core/character/configs/extra/<年>/<月>/distilled_profile.md` 由 journal 摘要服务按月度生成、
`persona_manager` 读取注入人设。它**两端都会写、内容必然不同**，因此 2026-10-13 起已从 git
跟踪中移除（否则每次同步都要解冲突），改由本脚本的 `persona` 分组搬运。

两端都是同一批记忆的 LLM 蒸馏、内容高度重叠，直接拼接会让文件无限膨胀，因此合并规则是
**非空优先、信息量大的优先**：

| 情况 | 结果 |
| --- | --- |
| 一侧纯空白 | 取另一侧（空壳绝不覆盖实质内容） |
| 只有标题的空壳 vs 有内容 | 取字符数更多的有内容一侧 |
| 两侧都有内容 | 取字符数更多的一份 |
| 长度相同 | 取字典序较大的一份 |

结果与合并顺序无关、对已合并结果幂等。同目录的 `legacy.json` / `reference_examples.json`
不属于蒸馏产物，仍纳入 git，不受影响。

> 源头也已加固：`distill_memory` 在 LLM 返回空内容时直接跳过写入，不再产出只有标题的空壳
> （Windows 侧就曾因此把 2026-09 的蒸馏记忆写成 28 字节空文件）。

### 直接读对端仓库（Linux 挂载了 Windows 的 D 盘时）

> 日常不必手动挂载，也不必手动同步：`./start.sh` 会**自动挂载** D 盘（幂等、失败不拦启动），
> 并在**启动前与退出后各同步一次**（`AUTARKIA_SYNC_ON_START=0` 可关闭）。
> 两次都避开主程序运行期，因此不存在与运行中程序抢写同一批文件的问题。
> 下面的命令是手动操作时的参考。

```bash
# 1) 先挂载。用 UUID 而不是设备名：两块 NVMe 的重启枚举顺序会互换，
#    D 盘曾从 /dev/nvme1n1p4 变成 /dev/nvme0n1p4，写死设备名会直接找不到盘。
#    分区 UUID 用 sudo blkid 查；必须「卸载后重新挂载」，见下方坑。
sudo mount -t ntfs-3g -o rw,uid=1000,gid=1000,umask=022 \
    /dev/disk/by-uuid/1264448764447011 /mnt/D

# 2) 同步。注意 --peer-study-root 指向「对端（Windows）的学习库」，不是本机的 ~/Study
python scripts/sync/learning_data_sync.py \
    --peer-root /mnt/D/AI/Autarkia \
    --peer-study-root /mnt/D/AI/Study \
    --apply
```

`--peer-data-root` 默认取 `<对端仓库>/companion_data/user_data`；
`--peer-study-root` 默认按跨平台镜像表推断（`D:\projects\study` ↔ `~/Study`），猜不出来会提示显式指定。

> **坑 1：FUSE 挂载不能用 `mount -o remount,rw` 打开写入。**
> 先 `mount -o ro` 挂载、再 `remount,rw` 时，`mount` 输出看着是 `rw`，但 ntfs-3g 守护进程
> 内部仍是只读，写入一律返回 `Input/output error`——连在挂载根 `touch` 一个新文件都是 ENOENT，
> 很容易误判成"卷坏了"。正确做法：`umount` 之后用 `mount -t ntfs-3g -o rw` 重新挂载。
>
> **坑 2：Windows 的"快速启动"本质是休眠**，开着它 ntfs-3g 只能只读挂载（见第一节第 4 点）。

### 首次同步实测（2026-10-13：D 盘 ↔ Linux 首次合并）

两端此前从未同步过（无基线），各自攒了数据，实测一次合并到位：

| 阶段 | 结果 |
| --- | --- |
| 首次 `--apply`（NTFS 只读，Windows 侧写入失败） | 拉取 197 / 合并 106 落到本机；回写 D 盘全部 `Input/output error` |
| 修正挂载后重跑 | 推送 71 / 拉取 48 / 合并 62 / 冲突 25，零失败 |
| 收敛验证（dry-run） | 本机 2203 项 / 对端 2197 项，**全部 SKIP**，两端完全一致 |

各端独有数据的典型形态：Linux 独有 09-27～09-30 的部分会话，Windows 独有 10-02～10-13 的
全部对话与记忆——这些由 `chat` / `memories` 的并集合并保留，没有丢消息。整文件覆盖类数据
（学习状态、每日计划等 25 个）按 mtime 取新的一方，旧版本留在 `*.sync-conflict-*` 副本里，
确认无误后可删。

### 挂到启动流程里

```bash
python scripts/sync/learning_data_sync.py --auto --apply
```

`--auto` 是无人值守模式：没有可用对端（没配 hub 且没传 `--peer-root`）时静默跳过，退出码 0。

**同步只能由 Linux 侧发起，所以必须在 Linux 上启停各跑一次**（`start.sh` 已默认这么做）：

| 时机 | 作用 |
| --- | --- |
| 启动前 | 把对端（Windows）新产生的复习进度 / 聊天记录拉过来 |
| 退出后 | 把本次会话产生的数据推给对端 |

为什么 Windows 那边不能自己同步：Linux 的数据落在 **ext4 根分区**上，Windows 原生读不了。
Windows 既看不到 Linux 的文件、也就没有可比对的对端，所以它的 `start.bat` 里加同步命令是
没有意义的（曾经在文档里这么写过，是错的）。

结果是「少一次都不完整」：

- 只在启动时同步 → 切到 Windows 看到的是**上次 Linux 启动时**的旧数据；
- 只在退出时同步 → Linux 自己拿不到 Windows 期间产生的进度。

若确实想让 Windows 也能发起同步，唯一的路子是改用 **hub 模式**：把中转目录放在两边都能读写的
NTFS 分区上（例如 `D:\Autarkia-sync`），Linux 用 `--hub /mnt/win_p4/Autarkia-sync`、
Windows 用 `--hub D:\Autarkia-sync`，各自与 hub 对账。

---

## 三、双系统代码同步（2026-10-21 起改走本地磁盘）

历史上用两条 push 触发的 GitHub Actions（`sync-local.yml` / `sync-local-linux.yml`）搬代码，
效果很差而且**一直是绿的**：双系统同一时刻只有一个在线，push 时对方必然离线，job 只能排队到
24 小时过期（`runner_name` 为空、started 与 completed 正好差 24 小时）；真跑起来时又因
「工作区有任何改动就跳过」而放弃，跳过还 `exit 0` 报成功。实测 2026-10-19 14:13 ～ 10-21 09:48
近 20 次 push：Windows 侧 10 次跳过 + 9 次排队过期 + 1 次空合并，Linux 侧 12 次跳过 +
6 次「无新增提交」，**两端各 0 次真正合并**。

现在改成和第一节同一个思路——**由能读到对端的那一侧主动去读，全部在本地磁盘**：

| 时机 | 系统 | 动作 |
| --- | --- | --- |
| 启动前 | Linux | `git fetch` Windows 工作副本 `/mnt/win_p4/AI/Autarkia` + `--ff-only` |
| 退出后 | Linux | `git push` 到同盘裸仓库 hub `/mnt/win_p4/AI/Autarkia-hub.git` |
| 启动前 | Windows | `git fetch` hub `D:\projects\autarkia-hub.git` + `--ff-only` |

- 挂点：`start.sh` 的 `sync_code` 函数（`AUTARKIA_SYNC_CODE=0` 关闭）、`start.bat` 启动前一行。
- 退出码：`0` 已同步或无需同步、`2` 被本地改动 / 分叉挡住（下次自动重试）、`1` 真错误。
  调用方一律**只警告不拦启动**，与第一节的挂载逻辑一致。
- 只处理 `main` 分支；当前不在 main 时静默跳过，避免误合到别的分支。
- 首次使用先建一次 hub（脚本 `push` 时也会自动 `git init --bare`）：

  ```bash
  # Linux
  git init --bare /mnt/win_p4/AI/Autarkia-hub.git
  # Windows（等价，二选一即可）
  git init --bare D:\projects\autarkia-hub.git
  ```

- 路径可用环境变量覆盖：`AUTARKIA_CODE_HUB`（hub 位置）、`AUTARKIA_CODE_PEER`（对端工作副本）；
  旧名 `XIAOYOU_CODE_HUB` / `XIAOYOU_CODE_PEER` 仍会被读取，便于 Linux 侧 `/etc/environment` 逐步迁移。
- ntfs-3g 挂出来的文件属主是 root，直接 `git fetch` 会报 `dubious ownership`；脚本对每个被访问的
  仓库临时加 `-c safe.directory`，不改用户全局配置。
- GitHub（`origin-private`）仍是备份 / 发布 / 部署源，不再参与双机同步；部署走
  `.github/workflows/deploy-linux.yml`（仅手动、勾选 `deploy` 才执行，部署前先拉平，拉不到即中止）。

手动排查：

```bash
python3 scripts/sync/code_sync.py status   # 只报告各端 HEAD，不动工作区
python3 scripts/sync/code_sync.py pull     # 启动前那一跳（两个系统都能跑）
python3 scripts/sync/code_sync.py push     # 退出后那一跳（只在 Linux 有意义）
```

---

## 四、组件库双向同步（2026-10-24）

`/home/user/Autarkia-Libs` 下是 9 个从主运行时抽出的独立仓库：

```text
Autarkia-Libs/
├── Autarkia-Cadence/ Io/ Msgqueue/ Textkit/ tool/   # 已上 GitHub + PyPI
└── unpublished/                                      # 只做双系统磁盘同步
    ├── Autarkia-Concurrency/
    ├── Autarkia-Emotion/
    ├── Autarkia-Personas/
    └── Autarkia-Vocab/
```

Windows 侧 `D:\projects\autarkia-Libs` 保持同样结构；Linux 通过 `/mnt/win_p4/AI/Autarkia-Libs`
直接读写这份工作副本。映射真源是 `config/libs_sync.json`（库文件 ↔ 主仓源文件，支持一对多），
不要再在别处维护路径表。

### 日常流程

1. 主仓改了映射文件（或组件库先改）：正常改代码，语义移植由 agent/人完成；
2. 按 RULES.md §4 跑 `auto_commit_push.py`：
   - 自动检测本次主仓改动命中了哪些组件库；
   - 组件库有改动就先跑组件库 pytest，再提交、推 GitHub（已发布 5 个）；
   - 同步到 Windows 工作副本（全部 9 个，ff-only）；
   - 主仓照旧提交推 `origin-private`。
3. 组件库先改、主仓后跟进：`libs_sync.py task` 生成双向移植清单，移植完后
   `libs_sync.py ack --lib <名称>` 更新基线，再走第 2 步。

```bash
python scripts/sync/libs_sync.py status    # 漂移 / 未推送 / Windows 是否一致
python scripts/sync/libs_sync.py task      # 生成待办（state/pending/<库>.md）
python scripts/sync/libs_sync.py push      # 手动提交推送组件库
python scripts/sync/libs_sync.py mirror    # Linux ↔ Windows 快进同步
python scripts/sync/libs_sync.py baseline  # 首次/重置基线
python scripts/sync/libs_sync.py ack --lib Autarkia-Io
```

`auto_commit_push.py` 新增参数：`--no-libs`（跳过）、`--strict-libs`（主仓改了但组件库没跟改时中止）、
`--libs-pypi`（版本号变化时 `uv build` + `uv publish`，需要 `UV_PUBLISH_TOKEN`）。
`start.sh` 启动/退出各跑一次 `mirror`，可用 `AUTARKIA_SYNC_LIBS=0` 关闭。

### 关键约定

- **同步的是 git 提交，不复制未提交文件**：谁改的谁先提交，镜像只做 `--ff-only`；
  对端脏工作树只有在「内容已等于目标提交」时才允许 checkout 后快进，否则报 blocked。
- **基线放在 Windows 分区** `.sync-state/`，双系统共用；哈希对 CRLF/LF 归一化，
  9 个库统一 `core.autocrlf=input`，避免换行符被误判成改动。
- **只自动移植「纯新增顶层符号」**：与基线相比已有函数/类逐字未变、只多出新函数/类，
  且新符号只依赖目标模块已有的名字时，脚本会直接追加并跑测试；修改已有符号、import
  变化、依赖缺失仍生成 diff 任务。组件库是通用化改写版（相似度普遍 0.1~0.8），
  逐字复制会破坏依赖注入与 stdlib-only 约束，这条边界不能放宽。

## 五、本机配置同步：`.env` 键级补缺 + CLI 就位（2026-10-25）

代码（git 提交）、运行数据（learning_data_sync）、组件库（libs_sync）三条通道都
覆盖不到 **gitignore 的 `.env`** 与 **装在系统里的 CLI**：前者不在提交里，后者是
平台相关二进制、无法跨系统搬运。`scripts/sync/env_sync/`（门面 `__init__` +
`env_merge` + `cli_setup`）补第四条通道，`start.sh` 启停各跑一次
（`AUTARKIA_SYNC_ENV=0` 可关闭）：

```bash
python -m scripts.sync.env_sync merge --peer-root /mnt/win_p4/AI/Autarkia --auto --apply
python -m scripts.sync.env_sync ensure-cli
```

### `.env`：键级并集、只补缺、不覆盖

| 情况 | 动作 |
| --- | --- |
| 键只在一侧存在 | 连同其上方段头注释与下方注释示例行补到缺的一侧（双向） |
| 两边都有、值相同 | 跳过 |
| 两边都有、值不同 | **保持本机现状，只打印差异报告**——路径类配置（如 Windows 盘符）本就该各写各的，整文件覆盖会互相破坏 |

- 解析只认活跃键（`KEY=VALUE`，行首无 `#`）；带 `#` 前缀的示例键当作注释文本随段搬运。
- 写回保持原文件换行风格（CRLF/LF）与 BOM，权限一律收紧到 0600（`.env` 含密钥，
  临时文件创建时就按 0600 建，先写 `.sync-tmp` 再原子替换）；非 UTF-8 的 `.env`
  整体跳过不猜编码。
- 合并幂等且与方向无关：补缺完成后两边键集合一致，再跑一次零改动。

> 语义取舍：值不同不覆盖意味着「在一侧改了已有键的值」不会自动传播（比如轮换了
> API key）。差异报告会列出这些键，看到后手动对齐即可——宁可少动，不静默覆盖。

### `ensure-cli`：CodeRabbit CLI 就位检查

- 本机有 `coderabbit` / `cr` 命令：打印版本，结束。
- 缺装：自动跑官方 `install.sh`（单次限时 90s；直连 `cli.coderabbit.ai` 失败会
  自动带本地代理 `http://127.0.0.1:7897` 重试一次），装到 `~/.local/bin`。
- Windows 侧 CLI 无法由 Linux 代装，仍需手动装一次；`.env` 里的
  `CODERABBIT_API_KEY` 则由 `merge` 自动带过去。

---

## 六、文件说明

| 文件 | 职责 |
| --- | --- |
| `core/utils/shared_roots.py` | 共享根 / 日志根 / 学习数据中转目录解析（唯一真源） |
| `scripts/sync/code_sync.py` | 双系统代码同步（`pull` / `push` / `status`，本地磁盘通道） |
| `scripts/sync/env_sync/` | 本机配置同步：`.env` 键级补缺合并（`merge`）+ CodeRabbit CLI 就位检查（`ensure-cli`），`python -m scripts.sync.env_sync` 调用 |
| `core/utils/project_root.py` | 项目根解析（零依赖，专门用来断开 `common → logger → config → shared_roots` 的导入环） |
| `scripts/sync/learning_data_sync.py` | 同步 CLI 入口 |
| `scripts/sync/learning_data/items.py` | 学习数据清单与对端路径布局 |
| `scripts/sync/learning_data/manifest.py` | 清单扫描（sha1 + mtime 指纹） |
| `scripts/sync/learning_data/planner.py` | 三向比对 → 同步计划 |
| `scripts/sync/learning_data/chat_merge.py` | 并集合并分派：聊天 JSONL（按 `event_id`）/ 当天 index.json（按条目） |
| `scripts/sync/learning_data/memory_merge.py` | 记忆并集合并（按 `id` / 指纹键取并集，同身份取更新的一份） |
| `scripts/sync/learning_data/transfer.py` | 执行传输、并集合并、冲突留档、写回基线 |
| `config/libs_sync.json` | 组件库 ↔ 主仓映射唯一真源（9 库、51 条映射） |
| `scripts/sync/libs_sync.py` | 组件库同步薄壳入口 |
| `scripts/sync/libs/manifest.py` | 清单解析与 Linux/Windows 路径解析 |
| `scripts/sync/libs/state.py` | 同步基线与 base 快照（CRLF 归一化） |
| `scripts/sync/libs/drift.py` | 双向漂移判定（主→库 / 库→主 / 冲突） |
| `scripts/sync/libs/publish.py` | 检测 → 测试 → 提交 → 推送 → 镜像编排 |
| `scripts/sync/libs/autoport.py` | 纯新增顶层符号的安全移植判定 |
| `scripts/sync/libs/autotransfer.py` | 按漂移方向执行自动移植并写回文件 |
| `scripts/sync/libs/gitops.py` | git 操作与 ff-only 双系统镜像 |
| `scripts/sync/libs/tasks.py` | 生成双向移植任务（含 before/after diff） |
| `scripts/sync/libs/safety.py` | 组件库公开仓的凭据扫描 |
| `scripts/sync/libs/testrunner.py` | 用主仓 venv 跑组件库 pytest |
| `scripts/sync/libs/pypi.py` | 版本变化检测与可选 PyPI 发布 |
| `scripts/git/auto_commit/libs_bridge.py` | `auto_commit_push.py` 接入组件库同步的桥 |
