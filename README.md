# VQCC 自动优化工作流

本仓库服务于 Google Verifiable Quantum Circuit Compilation，覆盖 DQI、InvSqrt
和 DFTHC-SOS 三个任务。它把研究、候选生成、官方验证、晋级、打包和定时提交放在
同一条可审计的流程中。目标是降低三题的官方成本、提高综合分、争取最终冠军，并
准备阶段奖励所需的可审阅公开材料。

所有任务的官方成本都是越低越好。流水线只会晋级成本更低且通过完整官方验证的候选；
本地成本、筛选结果或论文中的资源指标都不能代替平台成绩。

> 本 README 面向当前服务器上的现有部署。只克隆 Git 不能得到完整运行环境：
> `kickmix.so`、官方数据、历史电路和实验状态另行存放。迁移现有部署请看
> [迁移到另一台现有服务器](#迁移到另一台现有服务器)；接入新账号前先看
> [独立接入教程](docs/teammate-onboarding.md)，不要直接启动自动提交。

## 三分钟上手

1. 进入仓库根目录 `/root/project/vqcc`。当前部署使用 Conda `vqcc` 和 Python 3.13；
   不要使用裸 `python`，也不要修改 `base`。
2. 运行 `./automation/launch.sh dry-run`，只检查配置、时间窗口和环境，不调用模型，
   也不提交文件。
3. 运行 `./automation/launch.sh status` 查看调度器、最近运行和下一个窗口；运行
   `conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python automation/pipeline.py status`
   查看三题当前最优、提交记录和未知结果。README 不复制这些实时数据。
4. 要开始一次研究、优化或结果审查，直接要求 Codex 使用 `$vqcc-optimize` 并说明任务；
   项目 skill 会从当前最优和已有失败记录继续。要启停现有自动调度，使用下方
   [环境与常用命令](#环境与常用命令)。

完整流程是 `研究 → create → generate → validate → promote → prepare → reserve → record`。
生成和验证不会自动上传；只有通过门槛的新改进，才会在获准的提交窗口进入上传流程。

## 入口与目录

| 需要做什么 | 从哪里开始 |
|---|---|
| 了解长期约束和权限 | [AGENTS.md](AGENTS.md) |
| 让 Codex 研究、优化、复现或审查 | [项目 skill](.agents/skills/vqcc-optimize/SKILL.md) |
| 查看文件夹职责和新文件放置规则 | [项目文件结构](PROJECT_STRUCTURE.md) |
| 查看部署参数和时间窗口 | [automation/config.json](automation/config.json) |
| 查看研究线索和已知方向 | [docs/research.md](docs/research.md) |
| 使用私有 Web 控制台 | [控制台说明](web/README.md) |
| 查看控制台规格和验收范围 | [开发文档](docs/web-console-development.md) · [验收记录](docs/web-console-read-validation.md) |

| 路径 | 内容 |
|---|---|
| [`automation/`](automation/README.md) | 调度、队列、资源监督、科学流水线、Top-3 和提交控制 |
| [`generators/`](generators/README.md) | 三题生成器、变换、筛选、分析工具和同目录单元测试 |
| `verifiers/`、`sample_submission/`、`kickmix/` | 比赛提供的验证器、样例、数据和原生扩展；保持不变 |
| `submission/2026-10-29/` | 不可变的历史提交快照；新快照必须使用新目录 |
| `docs/`、`diagrams/` | 人工可读的实验/运维文档和可重新生成的架构图 |
| `tests/` | Web API、事件流、读取模型和资源投影的跨模块测试 |
| `artifacts` | 指向数据盘的链接，保存实验、运行、研究、提交包和状态 |
| [`web/`](web/README.md) | 私有控制台前后端；只负责查看和排队，不直接执行科学任务 |

完整的目录职责、状态文件所有权和新文件放置规则见
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。私有 Web 控制台的页面、参数、队列、
额度、接口与验收要求以开发文档为准；本地启动方法见控制台说明，已完成的数据验收
范围见验收记录。

## 运行边界和自动调度

| 项目 | 配置 |
|---|---|
| 算力 | 所有任务合计最多 20 CPU、180 GiB 内存、GPU 0 和 1；不新增付费资源 |
| 实验数据 | `/mnt/data2/vqcc`，项目内通过 `artifacts` 链接访问 |
| 优化窗口（北京时间） | 00:10–05:55、06:10–07:25、09:10–11:55、12:10–17:55、18:10–19:25 |
| 改进提交 | 每天 08:00、20:00 各检查一次，窗口各 45 分钟；每窗口最多一次尝试、每 UTC 日最多三次成功提交，仅提交已完整验证的新改进 |
| 结果查询 | 20:55；缺少平台评分时保持未知状态 |
| 截止 | 2027-01-21 07:59 北京时间；随后调度器自动停止 |
| 对外公开 | notebook、数据、源码、论坛消息、最终提交选择均先准备材料供用户审阅 |

优化窗口是允许工作的预算，不要求无收益地耗满。每个窗口至多启动一次；失败
记录留到下一窗口处理。每日查新覆盖旧帖新评论，论文和代码先核查来源，再安排
具体可复现实验。三个任务按预期综合分收益和实验成本分配资源。

未提交的已验证改进保留到下一个上传窗口，执行时选择当前最佳组合，无需再完成
一轮优化。没有改进就跳过；上传失败保留记录，不占每日成功提交额度。
成功提交以有效的 Kaggle 提交 ID 为准，评分状态另计，同一 ID 只计一次。
上传前还要核对平台团队记录，遵守官方每 UTC 日最多 5 次的额度；
本地每日三次成功提交限制和模型任务预算同时生效。

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

- 每题按官方成本选择产物不重复、证据有效的 Top‑3，固定为三条独立优化分支。
  三条分支的结果各自完成官方验证后，再基于三条分支的有效方案做同题组合优化；
  组合结果必须另外执行完整官方验证，不能沿用分支的 PASS。进度保存在
  `research/top3.json`，跨运行续跑；中途出现新最佳也不会丢弃尚未完成的分支。
  本轮完成后再更新 Top‑3；不足三个时记录缺额。提交仍采用每题已晋级的最佳候选。
  具体命令和阶段门槛见 [Top‑3 工作流](.agents/skills/vqcc-optimize/references/top3.md)。
- 所有可行优化都必须完成官方验证，包括公开代码改造和参数扫描中的每个可行变体。
  初筛可排除有明确正确性或资源违规证据的方案；预计成本高、收益小或收益不确定
  不能代替官方结论。尚未生成完整产物或来不及验证的方案保留在现有假设队列，
  记录候选 ID、剩余命令和原因，下次优化优先续跑。
- 本地实验生成成功后自动执行完整官方验证，控制台不再提供“仅生成与初筛”。
  新请求不能关闭验证；旧队列中的本地实验执行时也适用这一要求。
- `validate` 运行官方完整设置，绑定产物、验证器、运行环境、源码快照及报告哈希。
  成功检查在产物和相关环境不变时复用。失败、缩小规模筛选和独立复核分别记录。
- `promote` 只接受真实较低的官方成本。DQI 小于 2% 的改进默认需要独立随机
  复核；所有相关复核结果都会保留。2% 是可配置的本地筛选启发式，非比赛规定。
  InvSqrt 官方完整验证已覆盖全部合法输入，不例行追加随机输入全量重跑。
- `prepare` 组合三题的最佳已验证组件，校验 ZIP 结构和解压后哈希。平台当日名额用尽、
  没有改进、组合已尝试或存在不确定上传结果时跳过。`reserve` 在截止前按实时配额允许
  进入上传状态。实际上传和提交使用现有 Kaggle MCP。
- 若网络调用结果不明且没有提交 ID，保留预留记录并先只读对账，禁止盲重试。
  已知提交 ID 但缺评分记录为 `score_unknown`，不会伪称平台评测通过。

2026-10-29 的提交 `57763974` 只作为历史起点记录，计入其 UTC 日期的一次平台提交。
其三题本地 PASS 来自已保存报告和匹配的产物哈希；导入未重复运行科学验证。
该提交对账后状态为 COMPLETE、公开分数为 2.18204；这不是当前状态。最新候选、
提交和评分以 `pipeline.py status` 为准，本地成本不能代替平台评分。

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
