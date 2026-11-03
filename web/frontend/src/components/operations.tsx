import { ArrowRight, Clock3, FileText } from "lucide-react";
import type { RecordData } from "../api/client";
import { Card, date, reason } from "./ui";

export function QueueSummary({ queue }: { queue?: RecordData }) {
  return (
    <Card title="队列与下一次自动运行" className="queue-summary">
      <div className="queue-counts">
        <div>
          <strong>{queue?.queued ?? "…"}</strong>
          <span>个已排队</span>
        </div>
        <div>
          <strong>{queue?.blocked ?? "…"}</strong>
          <span>个等待条件</span>
        </div>
        <div>
          <strong>{queue?.active ?? "…"}</strong>
          <span>个活跃 / 待核实</span>
        </div>
      </div>
      <p>{queue?.message || "正在读取队列状态。"}</p>
      <div className="schedule-facts">
        <div>
          <Clock3 size={15} />
          <span>下一次自动优化</span>
          <strong>{date(queue?.next_optimization_at)}</strong>
        </div>
        <div>
          <Clock3 size={15} />
          <span>下一次例行对账</span>
          <strong>{date(queue?.next_reconcile_at)}</strong>
        </div>
      </div>
      <p className="muted">
        {queue?.schedule_note ||
          "自动任务在符合调度条件时入队；排队数量反映已经创建的作业。"}
      </p>
      <div className="budget-availability">
        <span>模型总余量：{queue?.model_available ?? "未知"} 次</span>
        <span>普通优化可用：{queue?.optimization_available ?? "未知"} 次</span>
        <span>提交模型可用：{queue?.submission_available ?? "未知"} 次</span>
      </div>
      <p className="muted">以上可用次数共享同一模型日预算，不能相加使用。</p>
    </Card>
  );
}

export function SubmissionActivity({ activity }: { activity?: RecordData }) {
  return (
    <div className="submission-activity">
      <div className="activity-heading">
        <span className="eyebrow">提交进度与最近结果</span>
        <time>
          {activity?.observed_at
            ? `观测于 ${date(activity.observed_at)}`
            : "尚未记录检查时间"}
        </time>
      </div>
      <p className="activity-message">
        {activity?.message || "正在读取最近的提交检查结果。"}
      </p>
      {activity?.blocked_reason && (
        <p className="next-action">
          <strong>具体等待原因</strong>
          {reason(activity.blocked_reason)}
        </p>
      )}
      {activity?.report_excerpt && (
        <div className="report-excerpt">
          <span>这次检查的报告记录</span>
          <p>{activity.report_excerpt}</p>
        </div>
      )}
      {activity?.next_action && (
        <p className="next-action">
          <strong>下一步</strong>
          {activity.next_action}
        </p>
      )}
      <div className="actions">
        {activity?.job_id && (
          <a className="button" href={`#/jobs?id=${activity.job_id}`}>
            查看这次任务
            <ArrowRight size={14} />
          </a>
        )}
        {activity?.report && (
          <a
            className="button"
            href={`/api/v1/artifacts/${activity.report.id}`}
            target="_blank"
            rel="noreferrer"
          >
            <FileText size={14} /> 阅读完整报告
          </a>
        )}
      </div>
    </div>
  );
}

export function SubmissionRules({ quota }: { quota: RecordData }) {
  return (
    <div className="submission-rules">
      <h3>什么情况下会提交</h3>
      <ol>
        <li>
          {quota.policy === "after_optimization" ? "优化结束后" : "到上传窗口时"}
          检查组合：三个组件的完整验证仍有效，并且比上次已提交组合更好。
        </li>
        <li>
          还有提交尝试和模型任务次数；本地每日最多{" "}
          {quota.daily_limit ?? "未知"} 次，按{" "}
          {quota.quota_timezone || "配置时区"} 计日。平台团队每日上限另行核对。
        </li>
        {quota.policy === "daily_windows" && (
          <li>
            北京时间每天 {(quota.submission_times || ["08:00", "20:00"]).join("、")}
            各检查一次，每个窗口最多一次上传尝试，失败也计次。未提交的改进保留到下一窗口，
            执行时选择当前最佳，无需再完成优化；没有改进就跳过。
          </li>
        )}
        {quota.policy === "after_optimization" && (
          <li>
            当日额度用完后保留尚未提交的最佳改进。北京时间次日 08:00 额度恢复后，
            等当前任务结束，优先补交执行时的最佳已验证组合，不必再完成一轮优化。
          </li>
        )}
        <li>
          没有缺少提交 ID
          的不确定上传；执行时重新准备最佳组合，并查询平台实际剩余额度，再预留和上传。
        </li>
      </ol>
      <p className="muted">
        本地配额记录帮助判断是否可启动，最终还须核对平台。没有改进、次数不足或平台查询未完成时，会保留原因，不自动重传。
      </p>
    </div>
  );
}
