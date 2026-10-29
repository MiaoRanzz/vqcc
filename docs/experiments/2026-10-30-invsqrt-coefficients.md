# InvSqrt 联合系数优化（北京时间 2026-10-30）

本轮完成确定性系数搜索，官方完整验证两份候选，并通过 `pipeline.py promote` 晋升
`20261030T061218-invsqrt-a9445a`。**InvSqrt 成本下降 4.510665%**，
本轮组合改善 1.550417%；相对已提交历史基线的本地组合改善为
**1.1495974712 倍**。这些是本地成本比，不是新的 Kaggle 分数。
本轮没有上传、提交、公开发布或更改计划；后续由独立 submit 模式检查资格、远端记录及 UTC 配额。

| 任务 | 当前最佳官方本地成本 | 候选 |
|---|---:|---|
| dqi | 1847158218915.007324 | `20261029T181345-dqi-18d183` |
| invsqrt | 1853715.898035 | `20261030T061218-invsqrt-a9445a` |
| dfthcsos | 3143055863.722955 | `20261030T002957-dfthcsos-8907aa` |

原 InvSqrt 成本 1941280.559862，本轮为 1853715.898035；Q 256→251，Toffoli
7327→7097。参数 delta/coef/square/product/result 为 **13/16/27/27/28**。
四张整数系数表记录在候选 `code/params.json`，其加载及 Horner/Newton 电路仍使用
原样 Apache-2.0 官方构造器。新适配器不修改验证器或模块全局系数。

## 实测与范围

- 324 组算术参数、每组 12,443 个确定性边界/分层输入：34 组通过、290 组失败。
  其中 delta14/coef14 不属于生产生成器接口，也在数值阶段失败；没有生成此配置。
  所有本轮 14/15 位系数试验失败，只否定所测坐标搜索与位数组合。
- 按 Q×Toffoli 下界选出的 12 组全部通过 3,133,452 个合法输入的数值检查。
  对这 12 组补算 64 位精确相位余量和旋转成本，仍由上述候选最低；估算与官方成本一致。
  这些筛查不替代电路验证，也没有改变随机种子或挑选电路哈希。
- 最优候选官方默认 **200,540,928 shots，PASS**，耗时
  64.96 秒；最坏误差/容差
  0.999138445911，x=1039483。
  余量较小已计入旋转合成成本，不声称对修改后的精度参数仍有效。
- 保留并官方验证的折中 `20261030T061709-invsqrt-2b636d`：仅 square_bits=28，
  Q=252，Toffoli=7161，成本
  1868250.199318，最坏误差/容差 0.816210544055；
  同样 200,540,928 shots、PASS，耗时 66.80 秒。
  成本稍高但余量更大，保留未晋升。
- 9 项生成器/表路由/分段边界测试通过。官方验证已覆盖每个合法输入，未追加重复随机输入全域检查。
  未变 DQI、DFTHC-SOS 的哈希绑定证据由 pipeline 复核，未重复运行昂贵验证。

最优电路 SHA256：`0d3737d024669c29eb0d1ef52d444236b3139fc1c72c3368e699ecd526b196f4`。
原始命令、源快照、验证器、环境与产物哈希在两份 `candidate.json`、`generation.json`
及对应 `official-*.json`。失败记录、12 组结果和两个非支配资源/误差折中分别位于
`screen/trials.jsonl`、`screen/full-domain.json`、`screen/tradeoffs.json`。

## 来源、版本与运行边界

生成及表搜索提交 `8a6f4f8161dd7ebc4e58ae9ce953c97eb2ade673`；
完整旋转成本筛查提交 `681869e7c0188f1365d7671f76fff623486d0bcd`。
父候选 `20261029T165239-invsqrt-0bd156`。来源、Apache-2.0 许可及逐文件 SHA256
见本轮 `sources.json` 和官方验证源快照；没有复制论坛或许可不明代码。

阅读 [Häner 等原论文 III、C.1–C.2](https://arxiv.org/html/1805.12445v1)：
初始近似与逐阶段精度值得联合优化。只借鉴方法，不把论文资源估计当作比赛成绩。
本轮没有 Kaggle MCP；最近评论列表、753403 与 753185 主题网页不可访问，搜索亦未提供
完整可用消息。新评论未知，旧成功游标保持不动，仅更新失败尝试时间，证据见 `sources.json`。

环境 Conda **vqcc**，解释器 **/root/miniconda3/envs/vqcc/bin/python**，prefix 已确认。
CPU affinity 0–18；官方验证最多 16 workers，数值筛查单进程，BLAS/OMP=1；
无 GPU、子代理或 detached workers。搜索 27.57 秒、余量成本筛查 15.28 秒；
所有大产物保存在 /mnt/data2/vqcc。未单独采集内存峰值，以 runner 完成后的监测报告为准。
既有用户改动保留；verifiers、kickmix、sample_submission、历史提交均未改动。

## 下一步与提醒

更新 `artifacts/research/hypotheses.json`：下一优先 DQI 长期 444-qubit B-bank 状态
压缩/重算，先证明恢复语义并测资源；化学保持 11-bit 量化残差筛查路线；
InvSqrt 后续研究直接优化最终 Newton 误差或有明确成本的乘法舍入，避免重跑已失败网格。

北京时间阶段节点 2026-11-21、2027-01-05 均为 07:59，奖项具体条件仍须核实；
最终截止 2027-01-21 07:59。每 UTC 日最多 5 次提交；公开材料和最多两份最终选择
仍须用户审阅。本轮不改变这些限制。最近已保存平台回执是历史 #57763974 的 2.18204，
不是本轮成绩；本轮没有查询或更新平台评分、排名。

检查点：2026-10-29T22:20:26.065521+00:00，早于运行截止 2026-10-30T03:38:49.060494+00:00。

## 复现

使用上述源提交、原 vqcc 环境及未修改的参考文件。先用 pipeline create 注册新候选，
将保留候选的 code/params.json 复制到新目录，禁止覆盖已有输出：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 conda run --no-capture-output -n vqcc \
  /root/miniconda3/envs/vqcc/bin/python generators/generate.py invsqrt \
  --output-dir NEW_OUTPUT --params NEW_PARAMS_JSON
conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  automation/pipeline.py --config RUN_CONFIG validate NEW_CANDIDATE_ID
```

搜索由 `generators/search_invsqrt_coefficients.py --output-dir NEW_SCREEN --stop-by UTC_TIME`
复现；余量成本比较由 `generators/screen_invsqrt_tradeoffs.py --full-domain FULL_DOMAIN_JSON
--output NEW_TRADEOFFS_JSON --stop-by UTC_TIME` 复现，均用同一解释器并标为筛查。
