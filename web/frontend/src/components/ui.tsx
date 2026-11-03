import { cloneElement, isValidElement } from "react";
import type { ReactElement, ReactNode } from "react";
import {
  ArrowUpRight,
  Circle,
  CircleCheck,
  CircleAlert,
  Clock3,
} from "lucide-react";
import type { RecordData, Snapshot } from "../api/client";
export const taskNames: Record<string, string> = {
  dqi: "DQI",
  invsqrt: "InvSqrt",
  dfthcsos: "DFTHC-SOS",
};
export const stateNames: Record<string, string> = {
  queued: "已入队",
  blocked: "等待条件",
  starting: "启动中",
  running: "运行中",
  cancel_requested: "正在停止",
  cancelled: "已取消",
  completed: "已结束",
  failed: "失败",
  timed_out: "已超时",
  resource_stopped: "资源停止",
  unknown: "待核实",
  PASS: "官方 PASS",
  FAIL: "官方 FAIL",
  pass: "官方 PASS",
  fail: "官方 FAIL",
  not_run: "未验证",
  unverified: "未验证",
  awaiting_validation: "待完整验证",
  screen_rejected: "初筛无改进",
  generation_failed: "生成出错",
  search_stopped: "搜索已停止",
  artifact_incomplete: "产物不完整",
  analysis_only: "仅分析 / 初筛",
  not_generated: "尚无验证产物",
  EVIDENCE_STALE: "证据需要复核",
  prepared: "已准备",
  upload_started: "已预留 · 结果待确认",
  score_unknown: "已接收 · 评分未知",
  submitted: "已接收",
  scored: "已评分",
  rejected: "平台拒绝",
  not_submitted: "已确认未创建提交",
  pending: "待复现",
  testing: "实验中",
  supported: "支持",
  refuted: "否定",
  inconclusive: "证据不足",
  unverified_source: "来源待核实",
  disabled: "已停用",
};
export const kindNames: Record<string, string> = {
  local_experiment: "本地实验",
  local_validate: "官方验证",
  local_promote: "晋级候选",
  prepare_preview: "组合预览",
  optimize: "智能体优化",
  smoke: "模型诊断",
  submit: "提交",
  reconcile: "平台对账",
};
export const validationReasonNames: Record<string, string> = {
  official_verifier_failed: "官方 verifier 执行失败",
  official_verifier_not_run: "尚未运行官方 verifier",
  recorded_screen_did_not_show_an_improvement: "已有初筛未显示改进",
  output_does_not_match_the_official_artifact_layout: "输出文件不符合正式 artifact 结构",
  no_official_artifact_generated: "没有生成正式验证 artifact",
  no_generation_or_verification_record: "没有生成或验证记录",
  measured_no_gain_in_tested_scope: "测试范围内实测无收益",
  no_lower_toffoli_count: "Toffoli 数没有降低",
  screened_out_no_proved_reduction: "未证明资源数能够降低",
  screened_out_no_width_gain: "宽度没有降低",
  rejected_initial_retraction_failed: "初始回缩步骤失败，方案被初筛拒绝",
  rejected_by_exact_quadratic_bound: "被精确二次界排除",
  bounded_deadline: "达到本次实验截止时间",
  iteration_limit: "达到迭代上限",
  line_search_stalled: "线搜索停滞",
  numerical_progress_stalled: "数值改进停滞",
  built: "artifact 已生成，尚未正式验证",
};
export const validationReason = (value: unknown) =>
  typeof value === "string" && value
    ? validationReasonNames[value] || value
    : null;
export const number = (v: unknown, digits = 2) =>
  typeof v === "number"
    ? v.toLocaleString("zh-CN", { maximumFractionDigits: digits })
    : "未知";
export const date = (v: unknown) =>
  typeof v === "string" && v
    ? new Date(v).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "未记录";
export const duration = (v: unknown) =>
  typeof v === "number"
    ? v >= 3600
      ? `${(v / 3600).toFixed(1)} 小时`
      : `${Math.round(v / 60)} 分钟`
    : "未记录";
export function Badge({ value }: { value?: string | null }) {
  const state = value || "unknown";
  const color = ["completed", "PASS", "pass", "scored", "supported"].includes(
    state,
  )
    ? "green"
    : [
          "failed",
          "FAIL",
          "fail",
          "rejected",
          "resource_stopped",
          "refuted",
          "screen_rejected",
          "generation_failed",
          "artifact_incomplete",
          "EVIDENCE_STALE",
        ].includes(state)
      ? "red"
      : ["running", "starting", "testing", "awaiting_validation"].includes(state)
        ? "blue"
        : "amber";
  const Icon =
    color === "green"
      ? CircleCheck
      : color === "red"
        ? CircleAlert
        : color === "blue"
          ? Circle
          : Clock3;
  return (
    <span className={`badge ${color}`}>
      <Icon size={12} />
      {stateNames[state] || state}
    </span>
  );
}
export function Card({
  title,
  aside,
  children,
  className = "",
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <div className="card-head">
          <h2>{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}
export function Heading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      <div className="actions">{actions}</div>
    </div>
  );
}
export function Empty({ children = "暂无记录" }: { children?: ReactNode }) {
  return (
    <div className="empty">
      <Circle size={23} />
      <p>{children}</p>
    </div>
  );
}
export function Notice({
  error,
  success,
}: {
  error?: string;
  success?: string;
}) {
  return (
    <>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {success && (
        <div className="notice success" role="status">
          {success}
        </div>
      )}
    </>
  );
}
export function Freshness({
  snapshot,
  error,
}: {
  snapshot?: Snapshot<unknown> | null;
  error?: string;
}) {
  return (
    <div className="freshness">
      <span>
        {snapshot ? `观测于 ${date(snapshot.observed_at)}` : "正在读取状态"}
      </span>
      {snapshot && (
        <span>
          快照 {snapshot.revision} · {snapshot.freshness} /{" "}
          {snapshot.consistency}
        </span>
      )}
      {error && (
        <span className="text-red">连接中断，保留上次快照：{error}</span>
      )}
    </div>
  );
}
export function KeyValues({ value }: { value: RecordData | null | undefined }) {
  return (
    <dl className="key-values">
      {Object.entries(value || {}).map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>
            {v === null || v === undefined
              ? "未记录"
              : typeof v === "object"
                ? JSON.stringify(v)
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Evidence({
  title = "依据与详情",
  value,
}: {
  title?: string;
  value: unknown;
}) {
  return (
    <details className="evidence">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function LinkButton({
  to,
  children,
  primary = false,
}: {
  to: string;
  children: ReactNode;
  primary?: boolean;
}) {
  return (
    <a className={`button ${primary ? "primary" : ""}`} href={`#${to}`}>
      {children}
      <ArrowUpRight size={15} />
    </a>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {isValidElement(children)
        ? cloneElement(children as ReactElement<Record<string, unknown>>, {
            "aria-label": label,
          })
        : children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="metric">
      <p>{label}</p>
      <strong>{value}</strong>
      {detail && <span>{detail}</span>}
    </div>
  );
}
export function download(
  name: string,
  content: string,
  type = "application/json",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
export function Pager({
  cursor,
  onNext,
  onReset,
}: {
  cursor?: string | null;
  onNext: (v: string) => void;
  onReset: () => void;
}) {
  return (
    <div className="pager">
      <button onClick={onReset}>回到第一页</button>
      <button disabled={!cursor} onClick={() => cursor && onNext(cursor)}>
        下一页 →
      </button>
    </div>
  );
}

const reasons: Record<string, string> = {
  WAITING_FOR_CURRENT_JOB: "等待当前任务结束",
  DAILY_MODEL_BUDGET_EXHAUSTED: "今日模型次数不足",
  PROTECTED_WINDOW: "等待旧版配置的调度时段",
  SUBMISSION_WINDOW: "等待提交窗口",
  RECONCILE_WINDOW: "等待对账窗口",
  DEADLINE: "运行时长超出比赛截止",
  CONFIG_RESOURCE_LIMIT: "排队配置超过当前资源上限",
  CONFIG_DURATION_LIMIT: "排队时长超过当前上限",
  SCHEDULER_STOPPED: "调度器已停止",
  AUTOMATION_PAUSED: "自动调度已暂停",
  INSUFFICIENT_DISK: "可用磁盘低于余量",
  EVIDENCE_STALE: "证据需要重新核验",
  NO_IMPROVEMENT: "相对已提交组合没有改进",
  ALREADY_ATTEMPTED_TODAY: "本地当日提交额度已用尽",
  DAILY_SUBMISSION_LIMIT_REACHED: "本地当日提交额度已用尽",
  ALREADY_ATTEMPTED_WINDOW: "当前上传窗口已经使用，等待下一窗口",
  ALREADY_ATTEMPTED_CANDIDATE: "当前组合已经尝试提交，等待新的已验证改进",
  SUBMISSION_NEEDS_RECONCILIATION: "存在不确定上传，须先对账",
};
export const reason = (value: string | null | undefined) =>
  value ? reasons[value] || value : "";
export const elapsed = (job: RecordData) =>
  job.elapsed_seconds ??
  (job.started_at &&
  (job.finished_at || ["running", "cancel_requested"].includes(job.state))
    ? Math.max(
        0,
        ((job.finished_at ? Date.parse(job.finished_at) : Date.now()) -
          Date.parse(job.started_at)) /
          1000,
      )
    : null);

export const submissionPolicyLabel = (policy?: string) =>
  policy === "after_optimization"
    ? "每次优化结束检查提交"
    : policy === "daily_windows"
      ? "每天两个窗口检查提交"
      : policy === "daily_window"
        ? "按配置窗口检查提交"
        : "提交策略未记录";

export const submissionSuccessLabel = (quota: RecordData) =>
  `${quota.successes_today ?? "未知"} / ${quota.daily_limit ?? "未知"}`;

export const submissionQuotaDetail = (quota: RecordData) =>
  `已取得平台提交 ID，评分状态另计；${quota.quota_basis === "successful_submissions" ? "失败上传不占每日成功额度" : "额度按上传尝试计算"}。今日尝试 ${quota.attempts_today ?? "未知"} 次，剩余额度 ${quota.remaining_today ?? "未知"} 次 · ${quota.quota_date ?? "未记录"}（${quota.quota_timezone ?? "未知时区"}）`;
