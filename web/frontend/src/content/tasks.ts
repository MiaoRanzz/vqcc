export interface TaskGuide {
  id: string;
  name: string;
  subtitle: string;
  summary: string;
  contract: string;
  formula: string;
  symbols: string;
  objective: string;
  directions: string[];
  validation: string;
  source: string;
}

// Explanations of the repository's competition contracts, not live measurements.
export const taskGuides: TaskGuide[] = [
  {
    id: "dqi",
    name: "DQI",
    subtitle: "Reed–Solomon 综合征解码与相位修正",
    summary:
      "这项任务把经典纠错码的解码计算放进量子电路：根据错误的综合征和给定掩码施加正确相位，随后恢复输入并清空临时量子位。优化的是这段可逆解码计算的资源成本。",
    contract:
      "固定实例使用 GF(2¹²) 上的 4,095 个位置、70 个综合征寄存器，最多对应 35 个错误位置。电路不能留下多余的工作位或错误相位。",
    formula: "成本 = R(ε₊) × Q² × Toffoli",
    symbols:
      "Q 是电路量子位数；Toffoli 是每次运行的平均 Toffoli 类门数；ε₊ 是采样失败率的统计上界；R 将该上界折算为重复开销。",
    objective:
      "降低量子位、门数与错误率共同决定的成本。量子位以平方进入公式，因此减少工作位可能很有价值，但不能只看 Q 或只追求零错误。",
    directions: [
      "复用解码工作区、缩短临时量子位的存活时间",
      "改进有限域算术、可逆多项式运算与根搜索",
      "在官方允许范围内评估截断造成的成本与失败率变化",
    ],
    validation:
      "默认完整验证抽样 102,400 次，检查输入恢复、工作位归零及相位。失败率上界必须小于 1/16；官方契约允许非零失败率。额外诊断不替代这项验证。",
    source:
      "verifiers/dqi/verify_submission_dqi.py · 模块说明、ProblemSpecDQI 与评分实现",
  },
  {
    id: "invsqrt",
    name: "InvSqrt",
    subtitle: "倒平方根相位计算",
    summary:
      "这项任务实现与 1/√x 成正比的量子相位。输入 x 来自基准中的动量差平方；电路需要算出足够精确的相位，再恢复输入并清理计算过程中使用的工作位。",
    contract:
      "对 22 位寄存器中的每个合法整数 x = 1…3,133,452，实现 exp(2πi / √x) 的相位。相位容差为 2⁻²⁴ / √x 圈，所有临时量子位最后都须归零。",
    formula: "成本 = Q × (Toffoli + T / 4)",
    symbols:
      "Q 是电路量子位数；Toffoli 是平均 Toffoli 类门数；T 是相位旋转所需的 T 门成本。T/4 将两类门折算到同一计量口径。",
    objective:
      "在全输入域精度达标的前提下，减少算术位宽、乘法和相位实现的资源。成本越小越好；减少一位精度并不一定能通过最坏输入的检验。",
    directions: [
      "调整近似函数、分段与系数精度",
      "优化定点乘法、截断位置与结果位宽",
      "复用算术工作区并降低相位合成开销",
    ],
    validation:
      "完整验证覆盖每一个合法 x，默认每个 x 运行 64 次，并检查相位、输入恢复和工作位。便宜的定点算术筛查有助于淘汰参数，但不等于正式电路验证。",
    source:
      "verifiers/invsqrt/verify_submission_invsqrt.py · 模块说明、ProblemSpecInvSqrt 与评分实现",
  },
  {
    id: "dfthcsos",
    name: "DFTHC-SOS",
    subtitle: "量子化学哈密顿量的分解与角度加载",
    summary:
      "这项任务针对固定的 FeMoCo76o113e 化学实例，用因子分解与一组角度加载电路表示哈密顿量。电路从地址读取旋转角度，分解与角度共同决定误差和整个块编码的资源成本。",
    contract:
      "基准包含 76 个空间轨道、113 个电子。提交内容包括 ANGLE 电路、因子分解和 Givens 树；角度实际加载的数值必须与分解一致，每个 ANGLE 电路最多使用 128 个量子位。",
    formula: "成本 = λ_eff × T_total × Q_total",
    symbols:
      "λ_eff = √[E_gap × (2Λ − E_gap)]。T_total、Q_total 计算整个块编码，还包含 PREPARE 和旋转的成本模型；不是单个 ANGLE 电路的门数与位数。",
    objective:
      "在化学精度和电路正确性都达标的前提下，联合降低有效归一化因子与整体资源。只降低 Λ、只压缩 ANGLE 位数，都不保证总成本下降。",
    directions: [
      "调整角度量化精度和 QROM 批次大小",
      "优化角度加载电路、Givens 树与工作区共享",
      "联合考虑分解维度、权重、残差与完整块编码成本",
    ],
    validation:
      "验证器恢复所有相关地址的角度字并检查相位、工作位与逆向清理，默认每地址抽样 64 次；同时检查哈密顿量残差。Λ > 49.0、E_gap > 3.914898 为严格条件，残差按官方 20 mHa 门槛及定义判定。",
    source:
      "verifiers/dfthcsos/SCORING_README.md · What a submission must do / Scoring；verifiers/dfthcsos/verify.py",
  },
];
