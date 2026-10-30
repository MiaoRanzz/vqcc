# 有界优化记录：公开 THC 因子与独立 ANF 编译

运行 `20261030T101500-optimize-96616a` 完成。DFTHC-SOS 官方成本从
**3143055863.722955 降至 821433551.3141971（下降 73.8651%）**，已由
`automation/pipeline.py promote` 晋升 `20261030T102135-dfthcsos-9cae8f`。
本轮本地组合改善 **1.5640833306 倍**，相对历史已提交基线 **1.7980662417 倍**。
这些是成本比，不是新的平台成绩；本轮上传和提交均为零。

| 任务 | 当前最佳本地官方成本 | 候选 |
|---|---:|---|
| DQI | 1847158218915.0073 | `20261029T181345-dqi-18d183` |
| InvSqrt | 1853715.8980346208 | `20261030T061218-invsqrt-a9445a` |
| DFTHC-SOS | 821433551.3141971 | `20261030T102135-dfthcsos-9cae8f` |

此次大幅改善来自采用原作者公开的较小化学分解，并用本仓库生成器重新编译、验证。
不把复现公开成果表述为新算法发现。DQI、InvSqrt 未变，已有绑定证据通过 pipeline
完整性复核，未重复昂贵验证。

## 实验与证据

1. 候选 `20261030T101703-dfthcsos-bf6e25`：原 R65/B60/C60 因子直接
   12→11 位舍入，E1/E2 为 **221.293/51.739 mHa**；新实现从原始向量逆向
   Givens 编码、重建一体本征向量后，为 **6.480/25.035 mHa**。
   两者都未通过 20 mHa 门槛，不运行官方电路验证。12 位重编码恢复父候选指标。
   这只否定所测固定因子的两种 11 位方法。
2. 原作者 Dmitrii Gluzdov 的 R1/B496/C384、11 位因子通过数值门槛。
   对本仓库独立 ANF 编译器筛查 **27 个 batch/prefix 组合：25 个可行、2 个超宽**，
   保留 **11 个成本/ANGLE 宽度非支配折中**。最优 batch=10、prefix=3，
   8 个 ANGLE 电路，最大 128 qubits；全块 **20286 Toffolis、833 qubits**。
3. 最优候选官方默认完整验证 **PASS：572 地址×64=36608 shots，15.68 秒**。
   E1=**6.931188715 mHa**，E2=**19.989998994 mHa**，
   Lambda=303.748239771，E_gap=3.914948810747，lambda_eff=48.610603740。
   预先指定 seed=`202610301015` 的任意非零目标 XOR/地址恢复/清洁工作位/相位检查
   通过：8 次重复、73216 次电路应用，0.32 秒。
4. 候选 `20261030T102653-dfthcsos-e41638`：独立实现四轮正交系数列旋转，
   751 次旋转保持增广系数 Gram 矩阵至 1e-12 内，角度词与树不变。
   lambda_h2 仅下降 2.1012e-6，预计相对成本改善 **3.481e-9**。
   收益不足以继续，保留筛查结果，**未官方验证、未晋升**。

生成器及边界/不变量测试共 **14 项通过**。所有官方与筛查证据严格分开。
源、环境、验证器和产物哈希见各候选 `candidate.json`、`generation.json`、
`official-*.json`；失败和折中保存在各 `screen/`、`screening-decision.json`。

## 来源、版本与限制

通过只读 Kaggle API 读取
[anazemcev notebook v3](https://www.kaggle.com/code/anazemcev/quantum-circuits-thc-joint-norm-881q-dqi)，
追溯至[原作者数据集第 4 版](https://www.kaggle.com/datasets/dmitriigluzdov/vqcc-femoco-public-factorization/versions/4)。
仅复用 `femoco_thc_r5.npz` 数值数据；未执行外部 notebook，未复制其生成代码。
原作者数据集元数据声明 Apache 2.0，版本文件列表、归属、许可文本与下载证据保留在候选
`code/upstream/`。源文件 SHA256 为
`a29cb868d59906bebcda50c1c44c14090d503665700d725027e25016544782fd`，
与已读 notebook 固定的原始因子哈希一致。

参考 [Low 等论文 v1 附录 D、B.7](https://arxiv.org/html/2502.15882v1) 的精度/完整资源权衡；
仅借鉴方法，未使用论文的随机舍入。比赛的残差门槛仍是判据。

本轮成功刷新 Recent 三页、44 个主题，读取 8 个主题及回复共 40 条消息。
论坛 API 最初请求字段误用导致 403；按公开前端的 `topicId` 字段纠正后成功，
未修改凭据、安全设置或权限。`sources.json`、原始响应和前后游标均在运行目录。
DQI 许可主题新增原作者允许使用的回复，以及参与者指向 SomeJoint 独立源码的说明；
仍需核对原作者声明和精确来源链，不能当作主办方奖项资格裁定。
InvSqrt 新线索是 63-qubit 家族的查表与乘法窗口重综合，尚未本地复现。
第三方报出的成绩、排名及 lambda 下界不视为本轮验证结论。

源代码提交：
`6eff956209ce1eb62b2e69d1becf2c922d33e1d1`（量化与布局筛查）、
`94167949a134d8990f8d326615b50fee37c6639f`（正交 gauge 生成器）。
官方候选证据以归档源码及逐文件哈希为准；gauge 后续代码不追溯改写旧验证。

环境为 Conda **vqcc**，解释器 **/root/miniconda3/envs/vqcc/bin/python**，prefix 已确认。
计算使用 CPU affinity 0–18；官方验证与独立检查分别限 0–15、16–18，BLAS/OMP=1。
无 GPU、子代理或 detached worker；所有启动任务均已退出。
180 GiB 内存上限未变，未单独记录进程峰值，以 runner 监测为准。
既有用户改动保留；官方验证器、历史基线、样例和 kickmix 未修改。

## 下一步与检查点

队列已调整为：**InvSqrt 可复现源码家族 → DQI 来源链核对及架构 → 最新 8 位化学因子/加载器**。
同时保留原 Gu BM 重算路线和本轮 11 个资源折中。避免继续打磨本次收益近零的固定因子 gauge。

化学 E2 距门槛仅约 0.010001 mHa，E_gap 距严格下限约 5.0811e-5 Ha；
修改权重或角度后必须重新建立证据。该官方完整 PASS 不代表平台已评分或获奖资格。
独立 submit 模式负责远端记录、配额与资格检查；本轮未准备新上传意图。
现有账本只有历史已评分提交和 prepared 记录，无新增不确定上传结果。

北京时间阶段节点：2026-11-21、2027-01-05 均为 07:59；最终截止
2027-01-21 07:59（UTC 2027-01-20 23:59）。奖项具体条件需届时核实。
每 UTC 日最多 5 次提交；公开材料和最多两份最终选择仍需用户审阅。
本轮截止 **2026-10-30 02:44:00 UTC**；完成检查点见运行目录 `checkpoint.json`。

运行目录：`/mnt/data2/vqcc/runs/20261030T101500-optimize-96616a`。
复现时用 pipeline create 新目录，再将保留的 `code/params.json` 和哈希匹配的上游 NPZ
交给 `generators/generate.py dfthcsos --output-dir NEW_OUTPUT --source-npz SOURCE --params PARAMS`，
使用上述 Conda 绝对解释器；随后 `pipeline.py --config RUN_CONFIG validate NEW_ID`。
不得覆盖现有候选。新 gauge 可由其独立候选参数复现，但不属于已晋升结果。
