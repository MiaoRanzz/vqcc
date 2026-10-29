# VQCC 自动优化工作流

面向 Google Verifiable Quantum Circuit Compilation 的 DQI、InvSqrt、DFTHC-SOS。
目标是提高官方综合分、争取最终冠军，并准备阶段奖励的可审阅公开材料。

入口是 [项目 skill](.agents/skills/vqcc-optimize/SKILL.md)，长期约束见
[AGENTS.md](AGENTS.md)，部署参数见 [automation/config.json](automation/config.json)。
可以在本项目直接要求 Codex 使用 `$vqcc-optimize` 做一次研究、优化或结果审查。

## 已授权的运行方式

| 项目 | 配置 |
|---|---|
| 算力 | 所有任务合计最多 20 CPU、180 GiB 内存、GPU 0 和 1；不新增付费资源 |
| 实验数据 | `/mnt/data2/vqcc`，项目内通过 `artifacts` 链接访问 |
| 优化窗口（北京时间） | 00:10–05:55、06:10–11:55、12:10–17:55、18:10–19:25 |
| 每日提交 | 20:00 开始，45 分钟窗口；每天最多一次、有完整验证的改进才提交 |
| 结果查询 | 20:55；缺少平台评分时保持未知状态 |
| 截止 | 2027-01-21 07:59 北京时间；随后调度器自动停止 |
| 对外公开 | notebook、数据、源码、论坛消息、最终提交选择均先准备材料供用户审阅 |

优化窗口是允许工作的预算，不要求无收益地耗满。每个窗口至多启动一次；失败
记录留到下一窗口处理。每日查新覆盖旧帖新评论，论文和代码先核查来源，再安排
具体可复现实验。三个任务按预期综合分收益和实验成本分配资源。

调度器是本项目独立进程，不启动或修改系统 cron。每分钟检查北京时间，所有
优化、提交和查询共享运行锁。CPU 通过继承的 affinity 限制到最多 20 核；内存
按进程树 RSS 总和监测，达到 170 GiB 提前停止，为 180 GiB 留余量。当前容器
不允许建立子 cgroup，因此内存控制是轮询停止机制，不是内核硬限制。子进程
采用进程组和 Linux subreaper 清理；禁止实验自行脱离监督器后台运行。

## 环境与常用命令

本机已有 Conda `vqcc`，Python `/root/miniconda3/envs/vqcc/bin/python`。
`kickmix.so` 要求 Python 3.13。`launch.sh` 每次通过 `conda env list` 定位环境，
再用 `conda run` 和绝对解释器启动，runner 核查 `sys.executable/sys.prefix`。

```bash
# 状态：进程是否存活、最近运行、下一可执行窗口
./automation/launch.sh status

# 仅查看配置和窗口，无模型调用、无提交
./automation/launch.sh dry-run

# 只读实测 shell、数据盘、Kaggle MCP
./automation/launch.sh smoke --seconds 300

# 安装/启动本项目调度器；可重复执行，不创建重复进程
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/install_schedule.py --install --start

# 停止本项目调度器及当前调度任务
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/install_schedule.py --remove

# 查看实验最优组合、提交记录及未知结果
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/pipeline.py status
```

服务器持续在线时，关闭聊天不会停止调度。**容器重启后，需要先确认数据盘挂载
和登录，再执行上述启动命令**；此容器没有可用的系统 init 服务。迁移到有进程
管理器的服务器时，可由该管理器调用 `automation/launch.sh daemon` 自动恢复。
不要同时保留两个负责提交的执行宿主。

## 实验、验证与版本

`pipeline.py create TASK --hypothesis ... --source ... --license ...` 创建隔离候选，
返回 `output` 目录。`generators/generate.py TASK --output-dir ... --params ...`
支持三题的初始生成器；进一步算法改写在 `generators/` 或候选 `code/` 中完成。
历史 `submission/2026-10-29/`、样例和官方验证器保持不变。

流水线依次为 `create → generate → validate → promote → prepare → reserve → record`。

- `validate` 运行官方完整设置，绑定产物、验证器、运行环境、源码快照及报告哈希。
  成功检查在产物和相关环境不变时复用。失败、缩小规模筛选和独立复核分别记录。
- `promote` 只接受真实较低的官方成本。DQI 小于 2% 的改进默认需要独立随机
  复核；所有相关复核结果都会保留。2% 是可配置的本地筛选启发式，非比赛规定。
  InvSqrt 官方完整验证已覆盖全部合法输入，不例行追加随机输入全量重跑。
- `prepare` 组合三题的最佳已验证组件，校验 ZIP 结构和解压后哈希。当天已用名额、
  没有改进或存在不确定上传结果时跳过。`reserve` 只在 20:00–20:45 窗口内允许
  进入上传状态。实际上传和提交使用现有 Kaggle MCP。
- 若网络调用结果不明且没有提交 ID，保留预留记录并先只读对账，禁止盲重试。
  已知提交 ID 但缺评分记录为 `score_unknown`，不会伪称平台评测通过。

2026-10-29 的已有提交 `57763974` 已作为历史起点记录，当天不会再次自动提交。
其三题本地 PASS 来自已保存报告和匹配的产物哈希；导入未重复运行科学验证。
平台元数据目前不返回评测状态和分数，不能由本地成本推算当前排名。

源码和说明使用本地 Git；每次研究运行提交可复现的改动。大文件不进入 Git。
实验包含父版本、参数、来源、失败记录、源码快照、验证报告和产物哈希。查看
代码更迭可运行 `git log --oneline`；查看具体实验使用其 `candidate.json`。

```text
artifacts/
  experiments/<id>/       候选、生成参数、源码快照和验证报告
  state/pipeline.json     三题最优、每日上传意图、回执及评分状态
  submissions/<token>/    正式候选 ZIP 及清单
  runs/<time>-<mode>/     模型运行摘要、中文报告、耗时与内存记录
  runtime/               调度器身份、互斥锁、每日执行记录和私有网络配置
```

日志不保存工具参数/返回原文；签名 URL 和凭证不进入 Git。运行使用 Codex 的
临时会话，长期状态以版本库和上述记录为准。不要手工修改状态来绕过提交门槛。
低于 20 GiB 可用空间时停止生成/运行，不自动删除历史最佳或正式提交。

## 迁移到另一台现有服务器

1. 停止源服务器调度器，确认没有不确定的上传请求。保存整个源码目录和实验数据
   的副本。Git **不包含** `kickmix.so`、官方样例、化学数据和历史电路；这些文件
   也必须随项目复制，不能只克隆 Git。已有未完成的 `prepared` 包到新日重新生成。
2. 将项目目录和 `/mnt/data2/vqcc` 分别复制到目标机。首次迁移推荐保留数据路径，
   便于历史归档路径继续可用；更换路径时修改 `storage_root`，重建 `artifacts`
   链接，并为准备上传的组合重新运行 `prepare`，不要复用旧绝对路径的上传包。
3. 不迁移 `runtime/transport-env.json` 或 Codex/Kaggle 凭证到他人账号。目标机
   使用自己的合法现有登录和网络配置。移除复制来的 `runtime/daemon.json`、
   `runtime/schedule.json`，保留每日提交台账和实验记录；不要清空提交历史。
4. 按项目记录准备已有的 Python 3.13 Conda 环境和依赖。环境不存在时先确认创建，
   不自动修改 base。更新配置中的 `python_executable`；也可以设置
   `VQCC_CONDA_BIN`、`VQCC_CONDA_ENV`，launcher 会传递解析到的 `VQCC_ENV_PREFIX`。
   新机器 ABI 必须能加载比赛提供的 kickmix；运行环境变化会触发重新验证。
5. 执行 `launch.sh dry-run`、`launch.sh smoke`，确认四项 readiness 都通过，
   检查 `pipeline.py status` 保留原提交记录，再安装并启动调度器。确认源服务器
   保持停止，防止双机同时提交。

同一数据目录仅允许一个调度器。更改配置后停止并重启调度器，让新预算和时间表
生效。迁移、重新登录和启动均复用原有额度，不隐式购买云服务或调用新的付费 API。

## 本次实施验证

流水线测试覆盖产物篡改、验证证据、重复提交、未知结果对账、历史回填及迁移。
生成器检查覆盖历史目录保护、失败不发布产物、InvSqrt 全域数值筛选和角度量化。
调度检查覆盖时区、提交窗口、截止、凭证脱敏与进程清理。

默认 InvSqrt 和化学生成结果与已有已验证基线逐字节一致；DQI 域转换检查通过，
本次未重复生成大体积 DQI 电路。上述工程检查不表示已获得新的比赛分数。

研究入口和当前待复现线索见 [docs/research.md](docs/research.md)。
