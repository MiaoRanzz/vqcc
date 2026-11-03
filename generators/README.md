# `generators/` 文件说明

本目录保存可复用、可复现的候选生成和分析代码。所有正式候选仍须通过
`automation/pipeline.py create` 建立隔离目录，并用 `pipeline.py validate` 完成官方验证。

## 入口和分组

| 文件或前缀 | 职责 |
|---|---|
| `generate.py` | 三题通用的基线生成入口；读取参数文件并写入指定候选输出目录 |
| `dqi_*`、`profile_dqi*`、`check_dqi*` | DQI 的可逆逻辑、缓存、uncompute、布局和资源分析 |
| `invsqrt_*`、`screen_invsqrt*`、`search_invsqrt*` | InvSqrt 的精度、分段、查表、生命周期和代数界分析 |
| `dfthcsos_*`、`screen_dfthcsos*`、`check_dfthcsos*` | DFTHC-SOS 的分解、规范、秩、拟合、量化和角度电路构造 |
| `import_public_bundle.py` | 导入带来源和许可证记录的公开候选包 |
| `boolean_cache_tasks.py` | 多个布尔缓存实验共享的任务生成辅助工具 |
| `vendor/` | 固定的第三方实现；每个来源必须保留许可证、致谢和 provenance |
| `test_*.py` | 与单个生成器紧密相关的数值、结构和边界测试 |

当前保持扁平文件布局，是为了兼容已有实验命令、源码快照和复现记录。新增实现应继续
使用任务前缀，而不是移动或重命名既有入口；若未来按子包拆分，应保留旧路径兼容包装器。

## 输入和输出边界

- 生成器源码进入 Git；生成的 `.kmb`、`.npz`、日志和大模型文件进入 `artifacts/`。
- 输出必须由命令行参数明确指定到候选目录，不能覆盖 `sample_submission/` 或历史提交。
- DFTHC-SOS 输入族必须保持 NPZ 与完整 ANGLE 文件集合一致。
- 公开实现必须记录来源、版本、许可证和本项目的适配步骤。
- 初筛只能证明具体违规或不可行；可行候选必须生成完整产物并执行官方验证。
- 一次性诊断代码可以保存在对应 run/candidate 的源码快照中；可重复使用后再提升到本目录。

## 测试位置

生成器自身的数学与结构测试保存在本目录，便于实现和测试一起迁移。跨模块流水线测试
放在 `automation/`，Web/API/读取模型测试放在根目录 `tests/`。
