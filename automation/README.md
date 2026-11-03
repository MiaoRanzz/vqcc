# `automation/` 文件说明

本目录是项目控制面。它决定何时运行、运行什么、如何监督进程，以及什么证据可以
晋级或提交；具体量子电路算法放在 `generators/`。

## 运行入口

| 文件 | 职责 |
|---|---|
| `config.json` | 当前部署的时间窗口、资源、环境、截止时间和提交额度；`agent_backend`（`codex`/`claude`）选择模型 CLI；`optimize_slot_minutes` 接力槽位、`submission_timezone` 提交时区、`validation_parallelism` 并发验证数、`top3_min_relative_gap`/`top3_preempt_fraction` Top-3 去重与抢占阈值；可选 `validation_job_seconds`（默认 7200）与 `agent_validation_queue_limit`（默认 3）约束代理排队的验证 |
| `launch.sh` | 解析 `vqcc` Conda 环境并以绝对 Python 路径启动 runner |
| `install_schedule.py` | 安装、启动或移除项目自有 daemon；不修改系统 cron |
| `runner.py` | 选择时段、持有共享锁、启动子进程、采样资源并清理进程树；`queue-validate --candidate ID` 让优化运行把长验证交给队列（`local_validate`，来源 `agent`），由 daemon 在模型任务之间执行 |

## 控制状态和执行

| 文件 | 职责 |
|---|---|
| `jobs.py` | 统一作业队列、配置版本、模型预算、调度控制、故障恢复和后续任务 |
| `search.py` | Top-3 周期、抢占刷新、`frontier` 公开最优成本与按差距的任务排序（含 `share`）；`brief` 启动视图、`handoff` 接力记录、`rank` 假设排序、`report` 中文报告骨架、`record --auto-no-change` 无可合并改进时关闭组合步；`brief` 的 `due.review` 按两日周期（`review_period_days`，默认 2，锚定 2026-11-01）提示复盘与论文阅读 |
| `model_config.py` | 作业类型、Codex/Claude Code 命令与模型参数、会话环境清理和生成器版本指纹 |
| `local_job.py` | 执行不调用模型的生成、验证、晋级和预览任务 |
| `events.py` | 向运行目录追加结构化时间线事件 |
| `kaggle_auth.py` | 在运行时读取合法凭据；不把令牌写入仓库或报告 |

## 科学与提交账本

| 文件 | 职责 |
|---|---|
| `pipeline.py` | 候选生命周期、完整官方验证、晋级、提交包、预留和回执 |
| `search.py` | 每题 Top-3 独立分支及组合阶段的持久化账本 |
| `submission_policy.py` | 本地成功提交额度、尝试记录和 UTC 配额日期计算 |

`pipeline.py` 不执行真实网络上传；上传由受监督的提交任务完成，再把脱敏回执交回
流水线记录。`search.py` 只管理搜索父代和阶段，不改变提交采用的单题最佳候选。

## 模型提示和测试

- `prompts/optimize.md`、`submit.md`、`reconcile.md`、`smoke.md` 定义受监督模型任务。
- `test_pipeline.py`、`test_search.py`、`test_submission_policy.py` 等测试对应同名模块。
- `test_runner_process.py` 专门覆盖进程树、超时和资源停止行为。
- `test_console_jobs.py` 覆盖统一队列、配置、额度和自动后续任务。

新增文件前先判断它属于控制面还是算法面：调度、账本、预算、门槛放这里；量子电路
构造和数学实验放 `generators/`；一次运行的临时代码放对应 `artifacts/runs/` 或候选目录。
