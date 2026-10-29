# 2026-10-30（北京时间）：DFTHC-SOS 精确 ANF 查表

本轮已完成并通过 `pipeline.py promote` 晋升候选 `20261030T002957-dfthcsos-8907aa`，父候选
`20261029T165927-dfthcsos-0cf768`。未上传、未提交；由独立 submit 模式按
`after_optimization` 再检查改进及 UTC 日配额，不能把本地晋升当作平台成绩。

| 当前最佳 | 官方本地成本 | 候选 |
|---|---:|---|
| DQI | 1847158218915.007324 | `20261029T181345-dqi-18d183` |
| InvSqrt | 1941280.559862 | `20261029T165239-invsqrt-0bd156` |
| DFTHC-SOS | 3143055863.722955 | `20261030T002957-dfthcsos-8907aa` |

化学成本由 3,247,752,448.668952 降至 3,143,055,863.722955，下降
**3.223663%**。
相对已提交历史基线的组合改善为 **1.1320460391 倍**，本轮组合增加
**1.098243%**；均是本地成本比，不是新的 Kaggle 分数。

将完整查表转换为 GF(2) 代数正规形，重算高地址单项式以复用工作位。
合法地址 a<3976 的任何子集索引 s 均满足 s<=a，因此可精确省去 s>=3976 的系数。
参数 brot/source_brot/batch_size/prefix_bits 为 12/12/9/5，lookup_family=anf。
整块 Toffoli 88,781→85,919，Q=742 不变；单个 ANGLE 不超过 128 qubit。
NPZ 字节不变，SHA256 `14d5cc25eb3bf82a9ccb87c811db28d127bef6d28697dd190dc1e875de3bfe69`；
error_1=0.0031851950317977845 Ha、error_2=0.018639570630974097 Ha、
lambda_eff=49.30136925057439，均与父候选一致。

证据：9 项生成器/边界测试通过；官方默认 254,464 shots 完整验证 PASS，耗时
43.16 秒。预先记录 seed=2026103003，覆盖全部
3,976 个地址、8 组任意目标字及两次应用，共 572,544 次电路应用，XOR、相位、
地址和工作位复原均 PASS（2.34 秒）。这是定向检查，
不声称覆盖所有测量轨迹。三项 incumbent 的证据哈希已复核，未重复运行未变任务的昂贵验证。

九组资源筛查中，一组超过 128-qubit 上限；其余八组保留实际计数。
保留 batch9/prefix6 的 127-qubit ANGLE 折中（估算成本 3,202,318,081.616916，
尚未官方完整验证）及更低宽度的参数记录。batch8/prefix2..4、batch9/prefix7..9
均不优于本轮前 incumbent，仅否定这些参数。初版筛查遗漏反向一遍的接口错误已标无效并归档；
修正后估算与正式成本一致，未以错误估算晋升。

环境：Conda `vqcc`，`/root/miniconda3/envs/vqcc/bin/python`，已核对 prefix；
CPU affinity 0–18，预算 19 核/180 GiB，本轮科学任务单进程、BLAS/OMP 各 1 线程，
最多同时两项；无 GPU、子代理或后台遗留。最终候选约 21.23 MiB，
生成 2.63 秒，修正后的资源筛查共 21.13 秒。
未独立采样内存峰值，以 runner 完成后的 result.json 为准。
UTC 2026-10-29T16:49:20.834576+00:00 已保存检查点，早于截止 2026-10-29 21:38:49。

源码提交 `5c5d88a16c552cd0cd4a130c9dfeb66d5734cfb3`；独立实现，接口沿用未修改的 Apache-2.0 官方代码。
来源、许可、文件哈希见本轮 `sources.json`；验证命令、源码快照与产物哈希见候选
`candidate.json`、`generation.json`、`official-c4391854.json`。
样例、验证器、kickmix、历史提交未修改；用户既有未提交改动保留。

研究：读了 [谱放大论文 B.5/B.7](https://arxiv.org/html/2502.15882v1) 的完整块成本说明，
以及 [数据查表资源折中原论文](https://arxiv.org/html/1812.00954v2)。没有复制论文代码，
论文资源估计不作为比赛实测。当前无 Kaggle MCP，最近评论列表和主题 753633、753185
网页均不可访问；旧帖的新消息仍未知，保留原成功游标，仅记录失败访问时间。

下一优先假设：联合调整 InvSqrt 四张三次系数表，尝试降低系数位宽，先全域数值筛查，
再做官方验证；保留 DQI 的 444-qubit B-bank 状态压缩/重算路线，以及化学 11-bit
量化残差筛查。队列与失败边界已更新至 `artifacts/research/hypotheses.json`。

提醒（北京时间）：阶段节点 2026-11-21、2027-01-05 均为 07:59，具体奖项条件须再次核实；
最终截止 2027-01-21 07:59。后续提交最多 5 次/UTC 日，需核对远端记录；公开材料及
最多两份最终选择须用户审阅。本轮未改变时间表、限额或最终选择。

## 复现

使用上述源码提交及 vqcc 环境。先通过 pipeline create 注册新候选（父候选和
来源/许可见 candidate.json），禁止向已有输出目录重建。将原候选
code/params.json 复制到新候选的 code/params.json；随后执行：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 conda run --no-capture-output -n vqcc \
  /root/miniconda3/envs/vqcc/bin/python generators/generate.py dfthcsos \
  --output-dir NEW_OUTPUT --params NEW_PARAMS_JSON
conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/pipeline.py --config RUN_CONFIG validate NEW_CANDIDATE_ID
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 conda run --no-capture-output -n vqcc \
  /root/miniconda3/envs/vqcc/bin/python generators/check_dfthcsos_xor.py NEW_OUTPUT \
  --seed 2026103003 --repeats 8 --report NEW_INDEPENDENT_REPORT
```

资源网格由 generators/screen_dfthcsos_anf.py 复现，输入原始 sample NPZ 和父候选
官方报告，输出新建的筛查目录。每次筛查均标记为非官方验证。
