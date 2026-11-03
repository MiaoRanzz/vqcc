import { Activity, ArrowRight } from "lucide-react";
import { useSnapshot } from "../api/client";
import {
  Badge,
  Card,
  Evidence,
  Freshness,
  Heading,
  LinkButton,
  Metric,
  date,
  number,
  stateNames,
  taskNames,
  submissionPolicyLabel,
  submissionSuccessLabel,
  submissionQuotaDetail,
} from "../components/ui";
import {
  QueueSummary,
  SubmissionActivity,
  SubmissionRules,
} from "../components/operations";
import Resources from "../components/Resources";
import { taskGuides } from "../content/tasks";

export default function Overview() {
  const { data, snapshot, error } = useSnapshot("/overview");
  if (!data)
    return (
      <>
        <Heading
          eyebrow="OPERATIONS / 01"
          title="实验总览"
          description="查看当前工作、可验证的改进，以及下一步。"
        />
        <Freshness error={error} />
      </>
    );
  const current = data.current_job,
    usage = data.usage || {},
    submission = data.submission || {};
  return (
    <>
      <Heading
        eyebrow="OPERATIONS / 01"
        title="实验总览"
        description="当前工作、三个任务的资源成本，以及提交检查进度。"
        actions={
          <>
            <LinkButton to="/tasks">了解三个任务</LinkButton>
            <LinkButton to="/workbench" primary>
              新建工作
            </LinkButton>
          </>
        }
      />
      <section className="status-banner">
        <div className="status-icon">
          <Activity size={26} />
        </div>
        <div>
          <div className="eyebrow light">当前执行</div>
          <h2>
            {current
              ? `${taskNames[current.task] || ""} ${current.stage_message || current.stage || stateNames[current.state] || "状态待核实"}`
              : data.scheduler?.paused
                ? "后续自动调度已暂停"
                : "当前没有运行任务"}
          </h2>
          <p>
            {current
              ? `${current.job_id} · 执行状态与科学验证结果分别记录`
              : data.queue?.message || "正在读取下一次运行安排。"}
          </p>
        </div>
        <LinkButton to={current ? `/jobs?id=${current.job_id}` : "/jobs"}>
          {current ? "查看当前任务详情" : "查看队列与下一次运行"}
        </LinkButton>
      </section>
      <div className="section-label">
        <h2>三个任务的本地最佳</h2>
        <span>官方资源成本 ↓ · 单位与公式各不相同</span>
      </div>
      <div className="grid three">
        {(data.best || []).map((best: any, i: number) => (
          <a
            href={
              best.id
                ? `#/experiments?id=${best.id}`
                : `#/tasks?task=${best.task}`
            }
            key={best.task}
            className="card candidate-card"
          >
            <div className="card-head">
              <span className="task-number">0{i + 1}</span>
              <Badge value={best.validation_status} />
            </div>
            <h3>{taskNames[best.task] || best.task}</h3>
            <p className="candidate-description">
              {taskGuides.find((task) => task.id === best.task)?.subtitle}
            </p>
            <div className="cost">{number(best.official_cost)}</div>
            <p className="cost-explanation">
              按本题验证器公式计算，越低越好；不是耗时或费用。
            </p>
            <div className="candidate-footer">
              <span>
                {best.improvement == null
                  ? "基线变化未记录"
                  : `较初始基线降低 ${number(best.improvement * 100)}%`}
              </span>
              <ArrowRight size={18} />
            </div>
          </a>
        ))}
      </div>
      <div className="card metrics-row">
        <Metric
          label="相对上次提交的组合改善 ↑"
          value={
            data.combined_improvement == null
              ? "未知"
              : `${number(data.combined_improvement, 6)}×`
          }
          detail={`三题成本比的几何平均；1× 为持平。比较基准 ${data.reference_id || "未记录"}`}
        />
        <Metric
          label="Kaggle 返回成绩 ↑"
          value={number(data.platform_score, 7)}
          detail={
            data.platform_score == null
              ? "平台尚无已登记的公开分数；与左侧本地改善倍数含义不同。"
              : `最近已知评分：提交 ${data.platform_score_submission_id || "未记录"} · ${date(data.platform_score_at)}。与左侧本地改善倍数含义不同。`
          }
        />
        <Metric
          label="当日成功提交 / 本地上限"
          value={submissionSuccessLabel(submission)}
          detail={submissionQuotaDetail(submission)}
        />
        <Metric
          label="今日已占用模型次数"
          value={`${usage.reserved ?? "未知"} / ${usage.limit ?? "未知"}`}
          detail={`已占用 / 模型日上限；剩余 ${usage.available ?? "未知"} 次。提交和对账也计入，本地实验不计入。`}
        />
      </div>
      <details className="card metric-explainer">
        <summary>这些数字怎么比较？</summary>
        <p>
          DQI、InvSqrt、DFTHC-SOS
          的成本公式和量级不同，跨任务只比较相对变化。单题百分比相对初始基线；组合倍数相对上次提交。例如组合
          1.10× 表示三项成本比的几何平均为 1.10，不代表所有题目各下降
          10%，也不是新的平台分数。
        </p>
        <a href="#/tasks">查看每题公式、优化目标与验证要求 →</a>
      </details>
      <div className="grid two">
        <QueueSummary queue={data.queue} />
        <Card
          title="当前提交进度"
          aside={<a href="#/submissions">打开提交中心 →</a>}
        >
          <SubmissionActivity activity={data.submission_activity} />
        </Card>
      </div>
      <Resources resources={data.resources || {}} />
      <Card
        title="提交规则"
        aside={
          <span className="subtle">
            {submissionPolicyLabel(submission.policy)}
          </span>
        }
      >
        <SubmissionRules quota={submission} />
      </Card>
      {data.alerts?.length > 0 && (
        <Card title="需要留意">
          {data.alerts.map((alert: any, i: number) => (
            <div className="alert-item" key={i}>
              <strong>{alert.message || alert.reason}</strong>
              <p>
                {alert.source} · {date(alert.observed_at)}
              </p>
              <a href={`#${alert.href || "/jobs"}`}>查看并处理 →</a>
            </div>
          ))}
        </Card>
      )}
      <Card title="从研究到提交" aside={<a href="#/tasks">了解任务背景 →</a>}>
        <div className="flow">
          {[
            ["研究假设", "/research", "未测量先验"],
            ["隔离实验", "/workbench", "参数与父候选"],
            ["完整验证", "/experiments", "官方成本与证据"],
            ["晋级最佳", "/experiments", "可靠改进"],
            ["组合提交", "/submissions", "改进与平台配额"],
            ["平台评分", "/submissions", "实际评测结果"],
          ].map(([title, link, sub], i) => (
            <a key={title} href={`#${link}`}>
              <span>{String(i + 1).padStart(2, "0")}</span>
              <strong>{title}</strong>
              <small>{sub}</small>
            </a>
          ))}
        </div>
      </Card>
      <Freshness snapshot={snapshot} error={error} />
      <Evidence title="总览快照依据" value={data} />
    </>
  );
}
