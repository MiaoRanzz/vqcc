2026-11-02 有界优化记录（运行 `20261102T155500-optimize-f50354`）

本轮按要求复现 Helios 公开组件，再改进其化学权重；公开代码比较另外发现并验证了 HW-09 DQI。两项晋升使本地官方成本推算的组合改进倍数增加 **0.0395124%**。这是本地验证结果，未取得新的 Kaggle 平台成绩。

| 任务 | 运行开始成本 | 当前完整官方验证成本 | 当前最佳候选 |
|---|---:|---:|---|
| DQI | 379,276,528,854.25 | **378,829,899,786.41** | `20261102T162525-dqi-fbc8e8` |
| InvSqrt | 100,568.49919456 | 100,568.49919456 | `20261101T001503-invsqrt-daf920` |
| DFTHC-SOS | 326,761,919.56 | **326,759,677.03** | `20261102T161745-dfthcsos-ceff73` |

组合倍数按三个成本比的几何平均计算：相对本轮开始为 `1.0003951241791933`，相对流水线记录的已提交成本为 `1.0004078184719896`，相对初始化基线为 `10.951342581027623`。各项哈希、成本与证据见[结果摘要](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/result-summary.json)。

[Helios notebook](https://www.kaggle.com/code/heliosli/the-dataset-is-public-now-enjoy) 固定为 v39、数据集 v45。DQI `92750bd6…` 和 InvSqrt `bce2948f…` 与已有组件一致，检查工件、源快照、运行环境及报告哈希后复用完整验证。前者先前一次独立检查成本超过旧最佳，继续保留不晋升结论，没有换种子重试。新化学 NPZ `aabde751…` 的十五个加载电路、角度字和树与当前 C40b 配方一致；原样导入 `97bff5`，完整官方成本为 `326800029.87183845`。这完成了公开工件复现，尚不等于从原始训练数据重建全部上游生成器。详细映射见[复现记录](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/reproduction.json)。

随后明确选用本地 `dfthcsos_manifold.py`、匹配的 C40b 模型缓存、block residual metric、`brot=8`、`freeze_below=1e-5` 和 error1 不等式，而非仅从 parent 名称推断配方。两个各 120 秒的有界拟合依次生成 `c2923b`、`ceff73`，成本为 `326762898.93`、`326759677.03`，均完整官方 PASS。末者降低本轮化学成本 `2242.53`，相对原样公开组件降低 `40352.84`，经流水线晋升。全过程保持既有加载电路、角度字和树；新权重 NPZ 为 `b5051c46…`。其[生成记录](/mnt/data2/vqcc/experiments/20261102T161745-dfthcsos-ceff73/generation.json)及候选 code/source 快照保存实际输入与命令。

[HW-09 notebook](https://www.kaggle.com/code/manwithacat/vqcc-hedge-wizardry-notebook) v10、数据集 v9 的 Apache-2.0 工件 `1698e864…` 改写了 24 处条件干净辅助位计算。方法依据是 [Khattar–Gidney 的条件干净辅助位构造](https://quantum-journal.org/papers/q-2025-05-21-1752/)；论文资源结论不作为比赛分数。实际完整验证测得 892 qubits、平均 Toffoli `399675.76193`，较本轮原最佳约少 471。默认及事先固定种子的三次独立检查各 102400 shots，全部 PASS，均无抽样 value/phase error，成本范围 `378829852884.84–378830109117.18`，全部低于旧最佳。所有结果及种子均保留，未追加选择性重试；[流水线晋升记录](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/dqi-promotion.json)与[四次验证复核](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/dqi-attestation.json)可查。上游 qhdl 生成引擎仍未公开，本轮复现的是固定编译工件。

两个有用的拒绝结果已改变下一轮选择：

- C39：同一 `42a6d0e6…` 起点解除 one-body、gap、成本限制后，120 秒精确 Hessian trust-ncg、120 秒系数 L-BFGS、至多 120 秒 QR 坐标 L-BFGS，two-body error 分别为 **21.116465、21.116372、21.116369 mHa**，均超过 20 mHa。QR 在约 77.5 秒停止；首个 Hessian 步的实际/预测下降比为 0.99518。停止这些同起点、固定角度字拟合；这不是 C39 全局不可行证明。[三组测量](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/curvature-comparison.json)。
- InvSqrt：五个窗口 `10572:11319`、`12464:13129`、`12808:13577`、`13219:13958`、`13642:14400`，完整保留首组 4/5 个 AND、旧目标值及仿射耦合后，第二组控制加保留输出的 67 列二次表示均满秩，交替矩阵秩 10，仍至少需要 5 AND。只排除此模板内的 4 AND 替代，不排除跨重置或新增非线性中间量。[精确边界记录](/mnt/data2/vqcc/experiments/20261102T160534-invsqrt-52b7cb/generation.json)。

本轮比较并固定八份源代码：Helios39、HW10、Yoyobar13、Alex82、Avazaku1、Kirill25、Leo9、Ehan4；重取榜单第 1、3 页，复用同日第 2 页，保留未读条目与来源缺口，未声称全量扫描完成。Yoyobar7 的新 DQI 改写授权范围仍未明确，未采用其更低成本声明。新论坛回复公布 Ehan 补丁授权及源地址，因此重试旧 403 并成功取得 v4；已读内容定位、跨重置生命周期和两处 3→2 AND 补丁，不复跑不变的 InvSqrt 全域检查。作者授权仅覆盖自身补丁，上游范围另行保留。[公开代码比较记录](/mnt/data2/vqcc/research/public-code/scans/2026-11-02/20261102T155500-optimize-f50354.json)。W44 周复盘已完成，本轮复用[既有周报](/mnt/data2/vqcc/research/weekly/2026-W44/report.md)，不重复执行。

下一轮按预期组合对数收益/总分钟排序：先以 10 分钟筛查当前 InvSqrt 中“未读取累加器 + 刚重置目标”的共享乘积，采用新恢复的生命周期思路；其次检查 HW-09 尚存的新结构改写；化学只保留一次有停止条件的 120 秒延续。所有预期收益和成功率明确是未测先验。实际输入、哈希、预算、拒绝边界已写入[假设队列](/mnt/data2/vqcc/research/hypotheses.json)。

新增矩阵自由 Hessian/QR 屏幕和保留多 AND 输出的二次下界实现，源提交 `e88c056`。**14 项相关单元测试及本轮 7 次完整官方检查全部通过**；不把数值筛查视为官方验收。使用 Conda `vqcc`，解释器 `/root/miniconda3/envs/vqcc/bin/python`；官方验证至多 16 workers，数值 BLAS 单线程，无 GPU 使用，限额 19 CPU/180 GiB。检查点位于[本轮目录](/mnt/data2/vqcc/runs/20261102T155500-optimize-f50354/checkpoint.json)，实验进程均受管理并已结束。

本模式未上传、未发布，也未改动调度。新最佳留给现有队列的下一个 20:00 上海窗口；最新已存提交 `57887546` 的状态仍为 `score_unknown`，不是已确认成绩。保留上海时间 2026-11-21、2027-01-05 07:59 里程碑与 2027-01-21 07:59 截止提醒；公开复现材料和最终提交选择仍须具体方案供用户审阅。
