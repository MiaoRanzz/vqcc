# 项目文件结构

本文是仓库目录职责的单一索引。运行流程见 [README.md](README.md)，长期约束见
[AGENTS.md](AGENTS.md)，具体优化方法见
[项目 skill](.agents/skills/vqcc-optimize/SKILL.md)。

## 顶层目录

```text
vqcc/
├── .agents/             Codex 项目工作流和参考规则
├── automation/          调度、队列、科学流水线和提交控制
├── generators/          三题的生成器、变换、筛选和分析代码
├── verifiers/           比赛提供的官方验证器
├── sample_submission/   比赛样例和生成所需的官方大文件
├── submission/          已提交组合的不可变历史快照
├── kickmix/             比赛提供的 Python 3.13 原生扩展
├── web/                 私有控制台前后端
├── tests/               Web/API/读取模型的跨模块测试
├── docs/                研究、实验、评审、运维和验收文档
├── diagrams/            从结构化规格生成的架构图产物
└── artifacts -> ...     数据盘入口；实验和运行状态不进入 Git
```

## 目录职责和修改边界

| 路径 | 负责什么 | 修改边界 |
|---|---|---|
| `.agents/` | `vqcc-optimize` 工作流及任务、提交、Top-3 等参考规则 | 只在项目流程或约束变化时修改；不能替代 `AGENTS.md` 的授权边界 |
| `automation/` | 调度器、作业队列、资源监督、候选流水线、Top-3 账本和提交策略 | 工程控制代码；入口和文件分工见 [automation/README.md](automation/README.md) |
| `generators/` | DQI、InvSqrt、DFTHC-SOS 的可复现生成和分析实现 | 不保存生成产物；分组和命名见 [generators/README.md](generators/README.md) |
| `verifiers/` | 官方完整验证和相关官方数据 | 视为只读比赛输入；修改会使既有验证证据失效 |
| `sample_submission/` | 官方样例电路和 DFTHC-SOS 输入数据 | 保持原样；文件体积大且不由普通 Git 克隆恢复 |
| `submission/` | 已提交组合、来源、清单、回执和验证报告的历史快照 | `submission/2026-10-29/` 不可改写；新快照使用新日期目录 |
| `kickmix/` | `kickmix.so` 和许可证 | 保持比赛提供版本；目标环境必须使用兼容的 Python 3.13 和 ABI |
| `web/` | FastAPI API、React 控制台、OpenAPI 契约和浏览器测试 | 只负责查看和排队；科学任务仍由 `automation/runner.py` 执行 |
| `tests/` | API、事件流、读取模型和资源投影的跨模块测试 | 不访问正式外部提交接口；fixture 必须与生产数据隔离 |
| `docs/` | 人工可读的研究记录、实验总结、周评审、运维说明和截图 | 测量结果要指向真实实验证据；文档结论不能代替官方验证 |
| `diagrams/`、`.seecode/` | 架构图规格、渲染结果和本地绘图配置 | 非运行依赖；生成产物可重新构建 |
| `artifacts` | 指向 `/mnt/data2/vqcc` 的软链接 | 只放运行数据和大产物；不要提交凭据、签名 URL 或锁文件到 Git |

## 根目录文件

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 当前项目的授权、资源、科学验证和提交硬约束 |
| `README.md` | 部署入口、常用命令和端到端运行说明 |
| `PROJECT_STRUCTURE.md` | 文件夹职责、状态所有权和文件放置规则 |
| `CHANGELOG.md` | 面向使用者的重要工程变更摘要 |
| `.gitignore` | 将凭据、缓存、二进制、大产物和运行状态排除在 Git 外 |
| `verifiable_circuit_compilation.pdf` | 比赛随附的参考材料；不是实时规则或当前成绩来源 |

## 数据盘结构

`artifacts` 不是普通源码目录，而是运行状态入口：

```text
artifacts/
├── experiments/<candidate-id>/  候选元数据、参数、源码快照、产物和验证报告
├── runs/<run-id>/               一次受监督运行的配置、事件、资源采样和报告
├── state/pipeline.json          三题最佳、历史基线和提交账本
├── research/                    假设队列、Top-3 周期、查新游标和评审证据
├── console/state.json           Web/统一队列、预算、配置版本和幂等操作
├── submissions/<token>/        正式候选 ZIP、清单和上传前证据
├── runtime/                     daemon 身份、共享锁和时段执行记录
└── tools/                       运行中构建或缓存的辅助工具
```

三份状态文件有不同所有者，不能互相替代：

- `state/pipeline.json` 由 `automation/pipeline.py` 管理科学最佳和提交事实。
- `research/top3.json` 由 `automation/search.py` 管理搜索父代和阶段进度。
- `console/state.json` 由 `automation/jobs.py` 管理作业、配置和预算。

## 新文件放置规则

1. 可复用的调度、门槛或提交逻辑放进 `automation/`，并在该目录的 README 登记。
2. 可复现的算法实现放进 `generators/`，文件名使用任务前缀；产物写入独立候选目录。
3. 一次实验的临时代码和完整源码快照放进 `artifacts/experiments/<id>/code/`，不要散落在仓库根目录。
4. 实验的机器可读证据留在候选目录；面向人的总结放进 `docs/experiments/`。
5. Web 跨模块测试放进 `tests/`；单一生成器的数值/结构测试可与生成器同目录保存。
6. 大电路、NPZ、日志、提交 ZIP 和运行缓存放进数据盘，不进入 Git。
7. 官方验证器、样例和历史提交不得通过“整理目录”移动或改写；需要新版本时新增路径并保留来源。
8. Kaggle/Codex 凭据、会话密钥、传输环境和签名 URL 不属于项目文件，不能进入源码或迁移包。
