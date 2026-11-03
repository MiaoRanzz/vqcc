import {
  Pause,
  Play,
  Square,
  ArrowLeft,
  RefreshCw,
  FileText,
} from "lucide-react";
import { mutate, useAction, useSnapshot } from "../api/client";
import type { Page, RecordData } from "../api/client";
import {
  Badge,
  Card,
  Empty,
  Evidence,
  Freshness,
  Heading,
  KeyValues,
  LinkButton,
  Notice,
  Pager,
  date,
  duration,
  elapsed,
  reason,
  kindNames,
  number,
  taskNames,
  stateNames,
} from "../components/ui";
import { QueueSummary } from "../components/operations";

export default function Jobs({ params }: { params: URLSearchParams }) {
  const selected = params.get("id");
  return selected ? (
    <JobDetail key={selected} id={selected} back={params.get("back") || ""} />
  ) : (
    <JobList params={params} />
  );
}

function JobActions({
  job,
  paused,
  action,
}: {
  job: RecordData;
  paused?: boolean;
  action: ReturnType<typeof useAction>;
}) {
  if (job.legacy) return null;
  if (["queued", "blocked"].includes(job.state))
    return (
      <button
        disabled={action.busy}
        onClick={() =>
          action.run(
            () =>
              mutate(`/jobs/${job.job_id}/cancel-queued`, {
                expected_state: job.state,
                revision: job.revision,
              }),
            "排队已取消",
          )
        }
      >
        取消排队
      </button>
    );
  if (["starting", "running"].includes(job.state))
    return (
      <button
        className="danger"
        disabled={action.busy}
        onClick={() => {
          if (
            confirm(
              `停止 ${job.job_id}（运行 ${job.run_id}）？未完成验证不算 PASS，已完成记录保留。后续自动调度${paused ? "已暂停" : "仍启用"}。`,
            )
          )
            action.run(
              () =>
                mutate(`/jobs/${job.job_id}/stop`, {
                  run_id: job.run_id,
                  revision: job.revision,
                }),
              "停止请求已受理，等待监督器确认",
            );
        }}
      >
        <Square size={12} />
        停止此任务
      </button>
    );
  return null;
}

function JobList({ params }: { params: URLSearchParams }) {
  const state = params.get("state") || "",
    cursor = params.get("cursor") || "0";
  const list = useSnapshot<Page<RecordData>>(
      `/jobs?state=${state}&cursor=${cursor}`,
    ),
    overview = useSnapshot("/overview");
  const action = useAction(),
    paused = overview.data?.scheduler?.paused;
  function filter(value: string) {
    location.hash = `/jobs${value ? `?state=${value}` : ""}`;
  }
  function paginate(value: string) {
    const p = new URLSearchParams(params);
    p.set("cursor", value);
    location.hash = `/jobs?${p}`;
  }
  const back = encodeURIComponent(params.toString());
  return (
    <>
      <Heading
        eyebrow="EXECUTION / 02"
        title="任务与队列"
        description="当前作业、等待原因和已完成记录。点击“查看详情”打开独立任务页面。"
        actions={
          <>
            <button
              disabled={action.busy}
              onClick={() =>
                action.run(
                  () => mutate(`/scheduler/${paused ? "resume" : "pause"}`),
                  paused ? "后续自动调度已恢复" : "后续自动调度已暂停",
                )
              }
            >
              {paused ? <Play size={15} /> : <Pause size={15} />}{" "}
              {paused ? "恢复自动调度" : "暂停后续自动任务"}
            </button>
            <LinkButton to="/workbench" primary>
              新建工作
            </LinkButton>
          </>
        }
      />
      <Notice error={action.error} success={action.success} />
      <QueueSummary queue={overview.data?.queue} />
      <p className="inline-note">
        {paused
          ? "自动调度已暂停，暂停期间不会自动提交。"
          : "暂停只影响后续自动任务，当前任务继续。"}{" "}
        手动作业仍遵守预算、验证与平台提交配额。
        {overview.data?.scheduler?.process_alive === true
          ? " 调度器已运行。"
          : overview.data?.scheduler?.process_alive === false
            ? " 调度器未运行，入队后暂不执行。"
            : " 调度器身份未记录。"}
      </p>
      <Card
        title="任务记录"
        aside={
          <select
            aria-label="筛选任务状态"
            value={state}
            onChange={(e) => filter(e.target.value)}
          >
            <option value="">全部状态</option>
            {[
              "queued",
              "blocked",
              "running",
              "completed",
              "failed",
              "cancelled",
              "unknown",
            ].map((s) => (
              <option key={s} value={s}>
                {stateNames[s] || s}
              </option>
            ))}
          </select>
        }
      >
        {list.loading && !list.data && (
          <div className="loading-state" role="status">
            正在读取任务列表…
          </div>
        )}
        {list.error && !list.data && (
          <>
            <Notice error={list.error} />
            <button onClick={() => list.refresh()}>
              <RefreshCw size={14} />
              重试读取
            </button>
          </>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>任务 / 来源</th>
                <th>题目</th>
                <th>状态</th>
                <th>已用 / 最长时长</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.data?.items.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <a href={`#/jobs?id=${job.job_id}&back=${back}`}>
                      {kindNames[job.kind] || job.kind}
                    </a>
                    <small>
                      {["automatic", "auto"].includes(job.origin)
                        ? "自动"
                        : "手动"}{" "}
                      · {job.job_id}
                    </small>
                  </td>
                  <td>{taskNames[job.task] || "自动分配"}</td>
                  <td>
                    <Badge value={job.state} />
                    <small>
                      {reason(job.blocked_reason) ||
                        (job.queue_position
                          ? `队列第 ${job.queue_position} 位`
                          : "")}
                    </small>
                  </td>
                  <td>
                    {duration(elapsed(job))} / {duration(job.max_seconds)}
                    <small>
                      配置{" "}
                      {job.config_revision == null
                        ? "未记录"
                        : `v${job.config_revision}`}
                    </small>
                  </td>
                  <td>{date(job.created_at)}</td>
                  <td>
                    <div className="actions">
                      <a
                        className="button"
                        href={`#/jobs?id=${job.job_id}&back=${back}`}
                      >
                        查看详情 →
                      </a>
                      <JobActions job={job} paused={paused} action={action} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {list.data && !list.data.items.length && (
          <Empty>
            {state
              ? "当前筛选没有匹配记录，可切换“全部状态”。"
              : "尚未创建任务。自动任务到窗口时入队，也可以从工作台创建手动作业。"}
          </Empty>
        )}
        <Pager
          cursor={list.data?.next_cursor}
          onNext={paginate}
          onReset={() => paginate("0")}
        />
      </Card>
      <details className="card maintenance">
        <summary>调度器运维</summary>
        <p>停止调度器仅在没有活跃或待核实作业时生效；Web 继续可读。</p>
        <div className="actions">
          <button
            disabled={action.busy}
            onClick={() =>
              action.run(
                () => mutate("/scheduler/start"),
                "调度器启动请求已受理",
              )
            }
          >
            启动唯一调度实例
          </button>
          <button
            disabled={action.busy}
            onClick={() =>
              action.run(
                () => mutate("/scheduler/stop"),
                "空闲调度器停止请求已受理",
              )
            }
          >
            停止空闲调度器
          </button>
        </div>
      </details>
      <Freshness snapshot={list.snapshot} error={list.error} />
    </>
  );
}

function JobDetail({ id, back }: { id: string; back: string }) {
  const detail = useSnapshot(`/jobs/${encodeURIComponent(id)}`),
    overview = useSnapshot("/overview"),
    action = useAction();
  const job = detail.data,
    run = useSnapshot(
      job?.run_id ? `/runs/${encodeURIComponent(job.run_id)}` : null,
    );
  const candidates: string[] =
    run.data?.candidate_ids || job?.candidate_ids || [];
  const waiting = job && ["queued", "blocked"].includes(job.state);
  return (
    <>
      <a className="back-link" href={`#/jobs${back ? `?${back}` : ""}`}>
        <ArrowLeft size={16} /> 返回任务列表
      </a>
      <Heading
        eyebrow="EXECUTION / TASK DETAIL"
        title={
          job ? `${kindNames[job.kind] || job.kind} · 任务详情` : "任务详情"
        }
        description={id}
        actions={
          job && (
            <JobActions
              job={job}
              paused={overview.data?.scheduler?.paused}
              action={action}
            />
          )
        }
      />
      <Notice error={action.error} success={action.success} />
      {detail.loading && !job && (
        <Card>
          <div className="loading-state" role="status">
            正在读取这次任务的状态与报告…
          </div>
        </Card>
      )}
      {detail.error && (
        <Card title="任务读取失败">
          <Notice error={detail.error} />
          <p className="muted">
            请求尚未成功，请重试或返回列表重新选择。读取失败不会取消或停止任务。
          </p>
          <button onClick={() => detail.refresh()}>
            <RefreshCw size={14} /> 重试读取任务
          </button>
        </Card>
      )}
      {job && (
        <>
          <Card title="这次任务的状态" aside={<Badge value={job.state} />}>
            <p className="lead">
              {reason(job.blocked_reason) ||
                job.stage_message ||
                (waiting
                  ? "已加入队列，等待调度器获得执行权。"
                  : job.state === "completed"
                    ? "本次运行已结束。实验是否通过验证、是否改进，请查看关联实验和运行报告。"
                    : stateNames[job.state] || "状态待核实")}
            </p>
            <KeyValues
              value={{
                题目: taskNames[job.task] || "自动分配",
                来源: ["automatic", "auto"].includes(job.origin)
                  ? "自动调度"
                  : "手动创建",
                创建时间: date(job.created_at),
                启动时间: job.started_at
                  ? date(job.started_at)
                  : "尚未启动 / 未记录",
                结束时间: date(job.finished_at),
                已用时长: duration(elapsed(job)),
                最长时长: duration(job.max_seconds),
                配置版本:
                  job.config_revision == null
                    ? "未记录"
                    : `v${job.config_revision}`,
                模型:
                  job.model ||
                  (["optimize", "submit", "reconcile", "smoke"].includes(
                    job.kind,
                  )
                    ? "历史未记录"
                    : "不调用模型"),
                推理强度: job.reasoning,
                服务档位: job.service_tier,
                停止原因: job.stop_reason,
              }}
            />
            {job.legacy && (
              <p className="inline-note">
                这是历史运行记录。缺少可确认的监督身份时，只提供阅读，不显示停止或取消操作。
              </p>
            )}
            {!job.run_id && (
              <p className="inline-note">
                {waiting
                  ? "任务尚未启动，因此还没有阶段事件和运行报告；排队本身不占用模型次数。"
                  : "这条记录没有运行 ID，暂时无法关联阶段事件与报告。"}
              </p>
            )}
          </Card>
          {job.run_id && run.loading && !run.data && (
            <Card>
              <div className="loading-state" role="status">
                正在读取运行记录…
              </div>
            </Card>
          )}
          {run.error && (
            <Card title="运行记录暂不可读">
              <Notice error={run.error} />
              <button onClick={() => run.refresh()}>重新读取运行记录</button>
            </Card>
          )}
          {run.data && (
            <>
              <Card
                title="运行报告与实验结果"
                aside={
                  run.data.report && (
                    <a
                      className="button"
                      href={`/api/v1/artifacts/${run.data.report.id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <FileText size={14} />
                      阅读完整报告
                    </a>
                  )
                }
              >
                {run.data.report ? (
                  <p>
                    运行报告保留了本次处理的工作、结果和下一步。提交任务请先查看报告中的平台查询、准备和上传结果。
                  </p>
                ) : (
                  <p className="muted">
                    尚未找到已保存的运行报告。报告缺失不能单独证明任务仍在运行。
                  </p>
                )}
                {candidates.length ? (
                  <div className="artifact-links">
                    {candidates.map((candidate) => (
                      <a key={candidate} href={`#/experiments?id=${candidate}`}>
                        查看关联实验：{candidate} →
                      </a>
                    ))}
                  </div>
                ) : (
                  <p className="inline-note">
                    本任务没有记录关联候选。运行结束状态不代表实验验证通过。
                  </p>
                )}
              </Card>
              <Card title="阶段时间线">
                <div className="timeline">
                  {(run.data.timeline?.length
                    ? run.data.timeline
                    : run.data.events || []
                  ).map((event: any, index: number) => (
                    <div key={event.event_id || event.id || index}>
                      <span>
                        {date(event.at || event.time || event.created_at)}
                      </span>
                      <strong>{event.message || event.type}</strong>
                      {event.progress?.total && (
                        <p>
                          {event.progress.completed} / {event.progress.total}{" "}
                          {event.progress.unit}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
                {!run.data.events?.length && (
                  <p className="muted">
                    历史没有结构化阶段记录，因此不估算进度百分比或剩余时间。
                  </p>
                )}
              </Card>
              <Card title="这次任务的资源采样">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>采样时间</th>
                        <th>CPU 核</th>
                        <th>进程树 RSS GiB</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(run.data.resources || [])
                        .slice(-20)
                        .map((sample: any, index: number) => (
                          <tr key={index}>
                            <td>{date(sample.at || sample.time)}</td>
                            <td>
                              {number(
                                sample.cpu_cores ?? sample.cpu_equivalent_cores,
                              )}
                            </td>
                            <td>
                              {number(sample.rss_gib ?? sample.sum_rss_gib)}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                {!run.data.resources?.length && (
                  <p className="muted">
                    这次运行没有记录可读取的资源样本；不使用整机当前资源代填历史任务数据。
                  </p>
                )}
                <p className="muted">
                  只展示已观测采样。RSS 为进程树求和，共享页可能重复计入。
                </p>
                <Evidence title="模型用量与统计覆盖" value={run.data.usage} />
              </Card>
            </>
          )}
          <Evidence title="任务 ID、配置快照与关联依据" value={job} />
        </>
      )}
      <Freshness snapshot={detail.snapshot} error={detail.error} />
    </>
  );
}
