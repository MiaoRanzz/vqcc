# 版本更迭

## 复盘周期、论文阅读与接力效率 — 2026-11-03

- 每周复盘改为每两天复盘（上海日历日，锚定 2026-11-01，`review_period_days` 可调）；
  复盘包含回顾、公开论文阅读和带增益/成功率/工时估计的优化思路建议，单轮上限 25%。
  新增 skill 参考 `review.md`、`papers.md`，论文库为 `research/papers/index.json`。
- 优化运行按固定六步执行并为固定开销设上限；`search.py brief` 启动视图、
  `handoff` 接力记录、`rank` 假设排序、`report` 中文报告骨架、
  `record --auto-no-change` 关闭无可合并改进的组合步；`allocation` 增加 `share`。
- `runner.py queue-validate` 把长验证交给队列（`local_validate`，来源 `agent`），
  由 daemon 在模型任务之间执行，同一候选去重、排队上限 3。
- `pipeline.py create --recipe-from` 复制父候选的生成配方供参考。
- runner 上下文移除 `one_submission_per_shanghai_date`，额度时区默认 UTC。
- 门槛规则只在 `AGENTS.md` 表述；skill、参考文档与优化提示改为引用。

## 搜索吞吐与调度 — 2026-11-03

- 提交改为每天一次 UTC 23:40（北京时间 07:40），窗口 20 分钟、每天最多一次成功；
  新增 `submission_timezone`。对账移到北京时间 09:00，且对账完成后其剩余时段交还优化。
- 优化全天按小时接力（`optimize_slot_minutes`），运行在对账前结束；排队中最多一个
  自动优化作业；每日模型作业上限 30；自动优化可按题开子代理。
- `pipeline.py validate` 只在读写状态时持有全局锁，按候选加锁；`validation_parallelism`
  限制并发验证并分配 verifier worker。
- Top-3 排除成本相差小于 `top3_min_relative_gap` 的近亲候选；验证过的领先者比全部
  父本低 `top3_preempt_fraction` 以上时，`plan` 抢占刷新该题周期。
- 新增 `search.py frontier` 记录各题公开最优成本，`plan` 输出按综合分差距排序的
  `allocation`；每轮优化先做增量公开代码检查。

## Claude Code 适配 — 2026-11-03

- 新增 `CLAUDE.md`（导入 `AGENTS.md`）、`.claude/settings.json` 和指向
  `.agents/skills/vqcc-optimize` 的 skill 链接；交互会话可用 `/vqcc-optimize`。
- 项目设置禁止编辑 `verifiers/`、`sample_submission/`、`kickmix/`、
  `submission/2026-10-29/`，禁止读取 `.env`、Kaggle 凭据和代理配置。
- runner 新增 `agent_backend`：`claude` 时以 `claude -p --output-format stream-json`
  无头运行，从 `result` 事件写 `report.md`；事件摘要仍不保存工具参数和结果。
  默认仍为 `codex`，行为不变。
- 控制台 token 统计同时汇总 Codex `turn.completed` 和 Claude Code `result`；
  启动调度器和子进程时清除交互式 Codex/Claude Code 会话变量。

## 工作流更新 — 2026-10-30

- 每个北京时间日期的首个可执行优化轮次，检查按分数降序发现的公开代码；
  保存版本、源码/依赖哈希和许可，把平台证据、作者声称与本地成本分开记录。
- 逐题复现、完整验证并通过晋级门槛后，将更好的公开实现作为后续优化父候选；
  复用未变化的证据，保留历史基线、失败记录和其他题的最佳结果。
- 每周一首个可执行优化轮次复盘上一完整周，依据收益、耗时和失败原因改进
  实验流程与 skill；验证和版本记录完成后才记为完成，并追踪下一周效果。
- 日查和周复盘共用原优化任务及预算，不新增后台循环，不改变现有提交策略。

## 0.1.0 — 2026-10-29

- 保存原始 2026-10-29 源码和验证记录，建立本地 Git；保留已有 Kaggle 提交
  `57763974`，平台评分未知。
- 增加项目 skill、AGENTS.md、三题可参数化生成入口和来源研究清单。
- 增加独立实验、完整官方验证、证据哈希、最优晋级、组合打包、每日提交预留和对账。
- 配置北京时间 20:00 的改进提交及 20:55 查询，使用项目专用调度进程。
- 增加资源监测、互斥、进程清理、私有日志及迁移操作说明。
- 通过 37 项工程测试及 skill 格式检查；普通环境和清空聊天会话变量的环境中，
  Codex 均成功完成只读本地目录及 Kaggle MCP 检查。
- 默认 InvSqrt 和 DFTHC-SOS 生成文件与已验证基线一致；DQI 域转换检查通过。
  本版本未产生新的平台提交或比赛评分。

后续源码更新由优化任务写入 Git。每次实验的父版本、参数、失败结果、源码快照、
验证报告和提交回执保存在数据盘，参见 README 中的数据布局。
