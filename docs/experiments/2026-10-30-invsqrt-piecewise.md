# InvSqrt 分段二次算术实验（2026-10-30）

本轮已通过 `pipeline.py promote` 晋升 **20261030T122425-invsqrt-d7c75b**。InvSqrt 官方本地成本
**1853715.898035 → 149805.967446，下降 91.918612%**；
本轮组合成本比改善 **2.3129772101 倍**，相对历史基线改善 **4.1588862393 倍**。
这些是本地成本比，不是新的平台分数。没有上传、提交或公开发布。

| 任务 | 当前最佳官方本地成本 | 候选 |
|---|---:|---|
| dqi | 1847158218915.007324 | `20261029T181345-dqi-18d183` |
| invsqrt | 149805.967446 | `20261030T122425-invsqrt-d7c75b` |
| dfthcsos | 821433551.314197 | `20261030T102135-dfthcsos-9cae8f` |

## 改变与证据

以 Houssem Alayet（marsyas）的 Apache-2.0 原始 notebook v2 为来源，替换原有四分段
三次近似加 Newton 的算术结构：256 分段二次拟合、signed-digit Horner、H/L 直接相位、
嵌套加法窗口。由源码重新拟合系数和 LP 相位角；没有采用公开的预生成电路或不透明拟合器。
收益属于复现既有公开算法；本轮新增 carry 参数实验未取得额外改善。

- 官方完整验证 **PASS，200,540,928 shots**：92 qubits，平均 Toffoli
  1313.000166370，44 次精细旋转；耗时
  72.81 秒。最坏误差/容差
  0.999905962854，x=2。
- 生成耗时 53.36 秒；先检查全部 3,133,452 个合法输入，
  再检查 5,311 个归一化/分段边界的相位、输入恢复和 scratch 清零。
  边界测量种子预设为20261030；不挑选电路哈希或 verifier seed。
- 数值最小余量 73,111,258 个2^-64相位单位；余量较小，但官方旋转合成成本已计入。
  官方验证已覆盖每个合法输入64次，未再追加冗余全域随机检查。
- 上游 exact-domain 后处理未执行；92-qubit生成结果未复现其他作者宣称的103k/63-qubit前沿。
  本地电路 SHA256：`c97569f50d762f1166c827d2568099af097d5b1e961566caf245687ba7caea66`。

## 保留的负结果与折中（以下均为筛查估计）

| carry target | 实际 Q | 样本平均 Toffoli | 估计成本 | 候选 |
|---:|---:|---:|---:|---|
| 88 | 89 | 1426.982 | 155065.41 | `20261030T122803-invsqrt-cd0841` |
| 84 | 92 | 1490.930 | 166175.48 | `20261030T122819-invsqrt-106791` |
| 80 | 92 | 1482.660 | 165414.69 | `20261030T122835-invsqrt-5362a6` |
| 76 | 92 | 1411.285 | 158848.19 | `20261030T122851-invsqrt-d3a598` |

四份变体复用完全相同的系数及相位映射，均通过数值和边界筛查；只有target88降到89qubits，
但增加门数使总成本更高，其余三份仍为92qubits。保留89qubit空间折中及所有失败假设，
未对被支配候选进行完整官方验证。本结论只针对上述具体窗口及参数，未否定其他布局。

## 来源与研究更新

Kaggle MCP成功读取Recent第一页（20条、总数44），并刷新753185、753738、753403的
正文和嵌套回复，覆盖旧帖的新活动；其他成功游标保留。新62-qubit主张暂未复现：其notebook v3
只展示打包和私有输入引用。63-qubit源码谱系仍待进一步核对；mrmeows v3 README是旧68qubit版本，
不能与最新页面混用。原始消息、版本与许可证据保存在本轮research和sources.json。

阅读[Häner等原论文III–V](https://arxiv.org/html/1805.12445v1)作为分段多项式和
寄存器/门数折中的方法背景，没有将论文资源估算当作比赛成绩。
采用的[原作者源码](https://www.kaggle.com/code/marsyas/vqcc-invsqrt-13-94x-full-source)
及其致谢链、Apache-2.0许可证均保留。源实现提交：
`d4dafebbd50490ecbca26a7b00ff4fc9f8881d3d`；后续文档提交只补充NOTICE链接、源清单和报告。

验证报告、精确命令、环境/验证器/源码/产物哈希在候选candidate.json和official-96078f61.json；
系数及相位角在code/coefficients.json。完整产物位于`/mnt/data2/vqcc/experiments/20261030T122425-invsqrt-d7c75b`。
本轮记录目录：`/mnt/data2/vqcc/runs/20261030T121300-optimize-06826d`。

## 运行边界与下一步

Conda环境 **vqcc**，解释器 **/root/miniconda3/envs/vqcc/bin/python**，prefix已核验。
CPU affinity0–18，拟合8进程、官方验证16workers、BLAS/OMP单线程；任务顺序执行，
没有GPU、子代理或detached workers。内存峰值未单独采集，以runner监测为准。
首次checkpoint写入因Conda捕获stdin未落盘，已用--no-capture-output修正并读回确认；
最早已确认检查点04:31:26 UTC，早于截止09:41:49 UTC。保留了原始工具失败和日志。
vendor导出仅去除writefile指令并追加一个末尾LF；该空行触发git diff --check。
八份模块其余字节与原作者源码完全一致，双向哈希已核对；保持已验证导出不再改写。
工作区既有修改未纳入本轮提交，官方verifiers/kickmix/sample及历史提交未改动。

本轮不准备ZIP、不上传、不提交。已有#57792124在本地账本仍是score_unknown；
应由独立submit/reconcile流程先核对该结果，再评估新最优及UTC配额。
最后保存的历史#57763974分数2.18204不是本轮成绩；本轮未查询平台分数或排名。

下一优先：核对并复现DQI projective extraction/streamed converter的完整许可和源码；
其次追踪8-bit化学因子与整块成本；InvSqrt保留低寄存器二次算术路线，避免重复carry网格。
队列已按预期log组合收益、成功概率和实现/验证成本更新，先验不是实测收益。

阶段节点（北京时间）：2026-11-21、2027-01-05均为07:59；最终截止2027-01-21 07:59。
公开里程碑材料及最多两份最终选择仍需用户审阅；每UTC日最多5次提交，本轮未更改计划或限制。

## 复现

先通过pipeline create登记新候选，禁止覆盖已有output。使用本轮源码版本和同一环境：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 taskset -c 0-18 \
  conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  generators/invsqrt_piecewise.py --output-dir NEW_OUTPUT --workers 8 --stop-by FUTURE_UTC_DEADLINE
conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/pipeline.py --config RUN_CONFIG validate NEW_ID
```

固定相位映射的carry变体可传`--fit-from ORIGINAL_CODE/coefficients.json --qcap 88`；
84/80/76同理。系数拟合依赖SciPy/HiGHS数值版本，实际系数和相位角已存档；跨环境
重拟合可能产生不同舍入，必须重新验证，不能借用本轮PASS。
