import { useState } from "react";
import { CircleCheck, CircleHelp, RefreshCw, Send } from "lucide-react";
import { mutate, useAction, useSnapshot } from "../api/client";
import type { RecordData } from "../api/client";
import HistoryChart from "../components/HistoryChart";
import {
  Badge,
  Card,
  Empty,
  Evidence,
  Freshness,
  Heading,
  KeyValues,
  Metric,
  Notice,
  date,
  number,
  reason,
  taskNames,
  submissionPolicyLabel,
  submissionSuccessLabel,
  submissionQuotaDetail,
} from "../components/ui";
import { SubmissionActivity, SubmissionRules } from "../components/operations";
export default function Submissions() {
  const read = useSnapshot("/submissions"),
    action = useAction(),
    [confirmation, setConfirmation] = useState<RecordData | null>(null),
    [kind, setKind] = useState("");
  const data = read.data,
    eligibility = data?.eligibility || {};
  async function preview(nextKind: string) {
    setKind(nextKind);
    await action.run(async () => {
      const result: any = await mutate("/jobs/preview", {
        kind: nextKind,
        max_seconds: nextKind === "submit" ? 1800 : 1200,
      });
      setConfirmation(result.data || result);
    }, "");
  }
  return (
    <>
      <Heading
        eyebrow="DELIVERY / 06"
        title="提交中心"
        description="本地验证、提交名额与平台评分，分别保留各自的事实。"
        actions={
          <button disabled={action.busy} onClick={() => preview("reconcile")}>
            <RefreshCw size={15} /> 查询平台（调用 Codex）
          </button>
        }
      />
      <Notice error={action.error} success={action.success} />
      <div className="card metrics-row">
        <Metric
          label="相对已提交组合"
          value={
            data?.combined_improvement == null
              ? "未知"
              : `${number(data.combined_improvement, 6)}×`
          }
          detail={`基准 ${data?.reference_id || "未记录"}`}
        />
        <Metric
          label="当日成功提交 / 本地上限"
          value={submissionSuccessLabel(eligibility)}
          detail={submissionQuotaDetail(eligibility)}
        />
        <Metric
          label="自动提交策略"
          value={submissionPolicyLabel(eligibility.policy)}
          detail={
            eligibility.policy === "after_optimization"
              ? `无固定时段；配额重置于北京时间 ${date(eligibility.resets_at)}`
              : `下一窗口：${date(eligibility.next_window)}（北京时间）`
          }
        />
      </div>
      <Card title="当前提交进度">
        <SubmissionActivity activity={data?.activity} />
      </Card>
      <Card title="提交规则">
        <SubmissionRules quota={eligibility} />
      </Card>
      <div className="grid two">
        <Card title="当前最佳组合">
          <div className="submission-best">
            {(data?.best || []).map((c: any) => (
              <div key={c.task}>
                <div>
                  <strong>{taskNames[c.task]}</strong>
                  <a href={`#/experiments?id=${c.id}`}>{c.id}</a>
                </div>
                <span>{number(c.official_cost)}</span>
              </div>
            ))}
          </div>
          <button
            disabled={action.busy}
            onClick={() => preview("prepare_preview")}
          >
            准备组合预览（本地）
          </button>
          <p className="muted">
            预览不锁定未来提交。实际执行时重新选择最佳并检查证据。
          </p>
        </Card>
        <Card title="提交资格">
          <ul className="checks">
            {(eligibility.checks || []).map((check: any, i: number) => (
              <li key={check.id || i}>
                {check.passed === true || check.ok === true ? (
                  <CircleCheck size={18} className="text-green" />
                ) : (
                  <CircleHelp size={18} className="text-amber" />
                )}
                <div>
                  <strong>{check.label || check.name || check.id}</strong>
                  <p>
                    {check.message ||
                      check.reason ||
                      (check.passed ? "已满足" : "待执行时确认")}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <button
            className="primary"
            disabled={action.busy || !eligibility.eligible}
            onClick={() => preview("submit")}
          >
            <Send size={15} /> 请求提交当前改进
          </button>
          <p className="muted">
            {eligibility.policy === "after_optimization" ? "每次优化结束" : "到上传窗口时"}
            检查已验证改进。提交会消耗一次顶层模型任务；模型预算、本地尝试上限与平台团队额度分别生效。
          </p>
        </Card>
      </div>
      {confirmation && (
        <Card title="确认加入队列" className="confirmation">
          <KeyValues
            value={{
              操作:
                kind === "reconcile"
                  ? "平台查询与登记（不重传）"
                  : kind === "submit"
                    ? "提交当前最佳组合"
                    : "本地准备预览",
              模型额度:
                kind === "prepare_preview"
                  ? "不调用模型"
                  : "启动前占用一次顶层模型任务",
              等待原因:
                reason(confirmation.blocked_reason) ||
                "执行时重新检查改进、验证与平台配额",
            }}
          />
          <Evidence title="预检依据" value={confirmation} />
          <div className="actions">
            <button
              className="primary"
              disabled={action.busy}
              onClick={() =>
                action.run(async () => {
                  await mutate("/jobs", {
                    kind,
                    max_seconds: kind === "submit" ? 1800 : 1200,
                  });
                  setConfirmation(null);
                }, "已入队，可在任务与队列中查看")
              }
            >
              确认加入队列
            </button>
            <button onClick={() => setConfirmation(null)}>取消</button>
          </div>
        </Card>
      )}
      <Card title="Kaggle 分数历史" className="platform-history">
        <p className="muted">
          仅展示平台已经返回的公开分数，越高越好；评分未知或结果待确认的提交仍保留在下方台账。
        </p>
        <HistoryChart
          title="Kaggle 公开分数历史"
          points={(data?.score_history || []).map((item: any, i: number, all: any[]) => ({
            value: item.platform_score,
            label: `提交 ${item.submission_id || "未记录"}`,
            at: item.submitted_at,
            current: i === all.length - 1,
          }))}
        />
        {(data?.score_history || []).length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>平台提交时间（北京时间）</th>
                  <th>平台 ID</th>
                  <th>公开分数 ↑</th>
                  <th>较前次变化</th>
                  <th>提交组合</th>
                </tr>
              </thead>
              <tbody>
                {[...(data?.score_history || [])].reverse().map((item: any) => (
                  <tr key={item.token || item.submission_id}>
                    <td>
                      {date(item.submitted_at)}
                      <small>评分记录于 {date(item.score_observed_at)}</small>
                    </td>
                    <td>{item.submission_id || "未记录"}</td>
                    <td className="numeric">{number(item.platform_score, 7)}</td>
                    <td className="numeric">
                      {signed(item.absolute_change)}
                      <small>{signedPercent(item.relative_change)}</small>
                    </td>
                    <td>
                      <Evidence title="三题候选与成本" value={{ selected: item.selected, costs: item.costs }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>暂无已返回的 Kaggle 公开分数</Empty>
        )}
      </Card>
      <Card title="每日提交台账">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>提交配额日期</th>
                <th>预留 / 提交时间（北京时间）</th>
                <th>平台 ID</th>
                <th>状态</th>
                <th>平台分数</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).map((item: any, i: number) => (
                <tr key={item.token || item.submission_id || i}>
                  <td>
                    {item.quota_date || "未记录"}
                    <small>{item.quota_timezone || "时区未记录"}</small>
                  </td>
                  <td>{date(item.reserved_at || item.receipt?.date)}</td>
                  <td>{item.submission_id || "尚未取得"}</td>
                  <td>
                    <Badge value={item.status} />
                  </td>
                  <td>{number(item.platform_score, 7)}</td>
                  <td>
                    <Evidence title="回执与来源" value={item} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data?.items?.length && <Empty>暂无提交台账记录</Empty>}
        <p className="inline-note">
          已有 ID 但评分未知，不单独阻止下一次合格改进；缺 ID
          的不确定上传须先对账。失败、超时或取消均保留尝试记录。
          {eligibility.quota_basis === "successful_submissions"
            ? "每日额度只计算取得有效提交 ID 的记录，上传失败不占成功额度。"
            : "每日额度按上传尝试次数计算。"}
          配额按上方日期口径计算。
        </p>
      </Card>
      <Freshness snapshot={read.snapshot} error={read.error} />
    </>
  );
}

const signed = (value: unknown) =>
  typeof value === "number"
    ? `${value > 0 ? "+" : ""}${number(value, 7)}`
    : "首次记录";

const signedPercent = (value: unknown) =>
  typeof value === "number"
    ? `${value > 0 ? "+" : ""}${number(value * 100, 5)}%`
    : "无前次分数";
