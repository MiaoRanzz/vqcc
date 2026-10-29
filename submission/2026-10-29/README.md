# 2026-10-29 比赛提交

最终压缩包：`submission.zip`。解压后即为本地官方 `sample_submission/` 的布局，ZIP 内不额外嵌套日期或 files 目录：

```text
dqi.kmb
invsqrt.kmb
dfthcsos/
  angle_k_0.kmb ... angle_k_9.kmb
  submission.npz
```

相同文件也可直接在 `files/` 中取得。压缩包仅包含这 13 个提交文件；源码、说明和报告放在压缩包外。文件清单及 SHA-256 见 `manifest.json`。已通过 Kaggle MCP 上传并正式提交，提交编号 `57763974`。平台接收回执见 `kaggle_submission_receipt.json`；最新查询结果见 `kaggle_submission_result.json`。平台评测状态与本地验证结果分别记录。

## 本次结果

| 题目 | 文件来源 | 官方完整验证 | 得分（越低越好） |
| --- | --- | --- | ---: |
| DQI | Anthropic 论文公开代码的适配版 | PASS；102,400 shots，0 次值错误、7 次相位错误 | 2,346,266,562,950.239 |
| invsqrt | 官方样例，逐字节不变 | PASS；200,540,928 shots | 2,076,774.233715282 |
| DFTHC-SOS | 官方样例，逐字节不变 | PASS；254,464 shots | 3,355,599,588.3155375 |

DQI 的误差上界为 `0.0011066102023661202 < 1/16`，置信参数 `log2_delta=-128`。额外测试了零错误和全部 4095 个单错误位置，共 4096 shots，值和相位错误均为零。

DQI 使用 566,880 个 Toffoli 门、1,842 个量子比特。相比官方样例的 5,725,461 个 Toffoli 门和 1,893 个量子比特，Toffoli 数下降约 90.1%。总操作数从 86,051,014 增至 114,741,138，不能解释成所有门都减少。其他两题没有进行论文算法适配或优化。

详细适配差异、论文来源及验证限制见 `ADAPTATION.md`；机器可读的官方结果位于 `validation/`。

## 复现

本次使用 Conda 环境 `vqcc`，解释器 `/root/miniconda3/envs/vqcc/bin/python`（Python 3.13.18）。比赛附带的 `kickmix.so` 要求 Python 3.13。依赖版本和 kickmix 哈希见 `validation/environment.json`，Python 依赖列表见 `source/requirements.txt`。

在 `/root/project/vqcc` 下运行以下命令。仅重新验证无需重新生成；生成命令会覆盖本日期 `files/dqi.kmb`，压缩包须另行重建。

```bash
conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python submission/2026-10-29/source/build_dqi.py

PYTHONPATH=/root/project/vqcc/kickmix OPENBLAS_NUM_THREADS=1 conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python verifiers/dqi/verify_submission_dqi.py submission/2026-10-29/files/dqi.kmb

OPENBLAS_NUM_THREADS=1 conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python submission/2026-10-29/source/validate_dqi_edges.py

PYTHONPATH=/root/project/vqcc/kickmix OPENBLAS_NUM_THREADS=1 conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python verifiers/invsqrt/verify_submission_invsqrt.py submission/2026-10-29/files/invsqrt.kmb --max-workers 16

PYTHONPATH=/root/project/vqcc/kickmix OPENBLAS_NUM_THREADS=1 conda run --no-capture-output -n vqcc /root/miniconda3/envs/vqcc/bin/python verifiers/dfthcsos/verify.py submission/2026-10-29/files/dfthcsos
```

所有评分使用未修改的项目官方验证器及默认赛题、精度、样本数、空 salt；倒平方根仅将并行进程数设为 16，不改变测试内容。没有进行哈希或种子筛选。本地验证通过不等于平台已经接受提交，也不是近似 DQI 电路在全部输入上正确的证明。

上游许可证和版本记录保存在 `source/upstream/LICENSE`、`source/upstream/PROVENANCE.json`。官方样例来源和一致性记录见 `validation/baseline_provenance.json`。
