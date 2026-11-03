import { useEffect, useState } from "react";
import { ExternalLink, Save } from "lucide-react";
import { mutate, useAction, useSnapshot } from "../api/client";
import type { RecordData } from "../api/client";
import {
  Card,
  Evidence,
  Field,
  Freshness,
  Heading,
  KeyValues,
  Metric,
  Notice,
  date,
  duration,
  number,
  submissionPolicyLabel,
} from "../components/ui";
const fields = [
  [
    "daily_model_limit",
    "每日顶层模型次数",
    0,
    100,
    "每个顶层模型任务启动占用一次，提交和对账也在其中。",
  ],
  [
    "reserve_submit",
    "提交任务的模型预留（次）",
    0,
    100,
    "在模型日总额内为提交保留；不是平台提交上限。",
  ],
  [
    "reserve_reconcile",
    "对账任务的模型预留（次）",
    0,
    100,
    "在模型日总额内为平台查询保留；不是已使用次数。",
  ],
  [
    "max_agent_seconds",
    "单次最长运行（秒）",
    30,
    19800,
    "后续创建的任务采用新快照。",
  ],
  ["cpu_limit", "CPU 核数上限", 2, 20, "所有并发计算与服务合计不超过 20 核。"],
  [
    "memory_stop_gib",
    "RSS 提前停止（GiB）",
    1,
    170,
    "监测值，不是内核硬限额。",
  ],
  ["memory_gib", "内存预算（GiB）", 1, 180, "包含计算、Web 与采样器。"],
  ["min_free_gib", "磁盘余量（GiB）", 20, 10000, "低于余量时阻止启动新计算。"],
] as const;
export default function Config() {
  const read = useSnapshot("/config"),
    usage = useSnapshot("/usage"),
    submissions = useSnapshot("/submissions"),
    [draft, setDraft] = useState<RecordData | null>(null),
    [baseRevision, setBaseRevision] = useState(0),
    [preview, setPreview] = useState<RecordData | null>(null),
    [dirty, setDirty] = useState(false),
    action = useAction();
  useEffect(() => {
    if (read.data && !dirty) {
      setDraft(
        read.data.history.find(
          (entry: any) => entry.revision === read.data!.revision,
        )?.config || read.data.config,
      );
      setBaseRevision(read.data.revision);
    }
  }, [read.data?.revision, read.data?.active_revision, dirty]);
  function set(k: string, v: unknown) {
    setDraft({ ...draft, [k]: v });
    setDirty(true);
    setPreview(null);
  }
  const u = usage.data || {};
  const quota = submissions.data?.eligibility || {};
  return (
    <>
      <Heading
        eyebrow="CONTROL / 07"
        title="配置与额度"
        description="版本化保存默认设置，运行中的任务保留自己的配置快照。"
        actions={
          <a
            className="button"
            href="https://chatgpt.com/codex/settings/usage"
            target="_blank"
            rel="noreferrer"
          >
            官方用量面板 <ExternalLink size={14} />
          </a>
        }
      />
      <Notice error={action.error} success={action.success} />
      <div className="card metrics-row">
        <Metric
          label="今日已占用模型次数"
          value={`${u.reserved ?? "未知"} / ${u.limit ?? "未知"}`}
          detail={`已占用 / 模型日上限；已启动 ${u.started ?? "未知"} 次，剩余 ${u.available ?? "未知"} 次。`}
        />
        <Metric
          label="累计模型运行"
          value={duration(u.model_seconds)}
          detail={`本地计算 ${duration(u.local_seconds)}`}
        />
        <Metric
          label="已观测 token"
          value={u.tokens ? number(u.tokens.input_tokens) : "未记录"}
          detail={
            u.tokens ? "输入 token；详细覆盖见下方" : "缺失用量不按 0 计算"
          }
        />
      </div>
      <Card title="为提交与对账保留的模型次数">
        <div className="reservation-grid">
          <div>
            <span>提交任务的模型预留</span>
            <strong>
              {u.reserve_submit ?? "未知"}
              <small> 次</small>
            </strong>
            <p>配置要求在模型日总额内为提交保留的次数。</p>
          </div>
          <div>
            <span>对账任务的模型预留</span>
            <strong>
              {u.reserve_reconcile ?? "未知"}
              <small> 次</small>
            </strong>
            <p>配置要求在模型日总额内为查询平台结果保留的次数。</p>
          </div>
        </div>
        <p className="reservation-explanation">
          上面是两个独立配置值，不是“已用 / 上限”。预留包含在每日{" "}
          {u.limit ?? "未知"}{" "}
          次模型预算中；总预算用完后，提交与对账都不能再额外启动。下面的提交额度单独计算。
        </p>
      </Card>
      <Card title="自动提交与平台配额">
        <KeyValues
          value={{
            提交策略: submissionPolicyLabel(quota.policy),
            本地每日提交上限: quota.daily_limit ?? "未知",
            本地额度计数口径: quota.quota_basis === "successful_submissions" ? "成功提交（有效提交 ID）" : "上传尝试",
            官方每日提交上限: quota.official_daily_limit ?? "未知",
            "上传时刻（北京时间）": quota.policy === "after_optimization"
              ? "优化结束后，无固定时刻"
              : (quota.submission_times || []).join("、") || "未记录",
            当前配额日期: `${quota.quota_date ?? "未记录"}（${quota.quota_timezone ?? "未知时区"}）`,
            本地剩余提交额度: quota.remaining_today ?? "未知",
            "配额重置（北京时间）": date(quota.resets_at),
          }}
        />
        <p className="muted">
          {quota.policy === "after_optimization" ? "每次优化结束" : "到上传窗口时"}
          检查是否有完整验证的改进，满足条件才提交。
          {quota.policy === "daily_windows" && "每个窗口最多一次尝试；未提交的改进保留到下一窗口。"}
          {quota.quota_basis === "successful_submissions" && "上传失败不占每日成功提交额度；结果不明时先对账。"}
          本地提交上限、平台团队额度和顶层模型任务次数分别检查。提交与对账仍消耗模型次数，不自动增加模型预算。
        </p>
      </Card>
      <Evidence
        title="原始 token 与统计覆盖（不估算费用）"
        value={{ tokens: u.tokens, coverage: u.coverage }}
      />
      <div className="notice info">
        当前默认 v{read.data?.revision ?? "…"} · 生效版本 v
        {read.data?.active_revision ?? "…"} · 当前运行采用{" "}
        {read.data?.running_config_revision == null
          ? "未记录"
          : `v${read.data.running_config_revision}`}{" "}
        · {read.data?.apply_status || "等待读取"}
      </div>
      {dirty && read.data?.revision !== baseRevision && (
        <div className="notice error">
          配置已由其他操作更新。当前草稿仍基于 v{baseRevision}；保存会提示冲突。
          <button
            onClick={() => {
              setDirty(false);
              setPreview(null);
            }}
          >
            重新载入最新配置
          </button>
        </div>
      )}
      {draft && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action.run(async () => {
              const result: any = await mutate("/config/preview", {
                config: draft,
                expected_revision: baseRevision,
              });
              setPreview(result.data || result);
            }, "");
          }}
        >
          <Card title="后续工作默认设置">
            <h3>项目模型</h3>
            <div className="form-grid">
              {[
                ["model", "模型"],
                ["reasoning", "推理强度"],
                ["service_tier", "服务档位"],
              ].map(([key, label]) => (
                <Field
                  key={key}
                  label={label}
                  hint="项目专用配置，不修改全局 Codex 设置。"
                >
                  <input
                    required
                    value={draft[key] || ""}
                    onChange={(e) => set(key, e.target.value)}
                  />
                </Field>
              ))}
            </div>
            <h3>模型次数与机器预算</h3>
            <div className="form-grid">
              {fields.map(([key, label, min, max, hint]) => (
                <Field key={key} label={label} hint={hint}>
                  <input
                    required
                    type="number"
                    min={min}
                    max={max}
                    step="1"
                    value={draft[key] ?? ""}
                    onChange={(e) => set(key, Number(e.target.value))}
                  />
                </Field>
              ))}
              <Field label="允许使用的 GPU">
                <select
                  value={(draft.gpu_ids || []).join(",")}
                  onChange={(e) =>
                    set(
                      "gpu_ids",
                      e.target.value
                        ? e.target.value.split(",").map(Number)
                        : [],
                    )
                  }
                >
                  <option value="0,1">GPU 0 和 1</option>
                  <option value="0">仅 GPU 0</option>
                  <option value="1">仅 GPU 1</option>
                  <option value="">不使用 GPU</option>
                </select>
              </Field>
            </div>
            <Evidence title="调度与运维设置" value={read.data?.deployment} />
            <p className="muted">
              资源下调会重新约束已排队任务；当前任务继续采用原快照。存储、解释器与认证变更使用停机迁移流程。
            </p>
            <div className="form-footer">
              <span>基于 v{baseRevision}</span>
              <button type="submit" className="primary" disabled={action.busy}>
                预览配置差异
              </button>
            </div>
          </Card>
        </form>
      )}
      {preview && (
        <Card title="保存配置新版本" className="confirmation">
          <Evidence title="配置差异与生效范围" value={preview} />
          <button
            className="primary"
            disabled={action.busy}
            onClick={() =>
              action.run(async () => {
                await mutate("/config/revisions", {
                  config: draft,
                  expected_revision: baseRevision,
                });
                setPreview(null);
                setDirty(false);
                await read.refresh();
              }, "配置新版本已保存；检查生效状态并按需应用")
            }
          >
            <Save size={15} /> 确认保存新版本
          </button>
        </Card>
      )}
      <Card title="配置历史">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>版本</th>
                <th>保存时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {read.data?.history?.map((entry: any) => (
                <tr key={entry.revision}>
                  <td>
                    v{entry.revision}
                    {entry.revision === read.data?.active_revision
                      ? " · 当前生效"
                      : ""}
                  </td>
                  <td>{date(entry.created_at)}</td>
                  <td>
                    <div className="actions">
                      <button
                        onClick={() => {
                          setDraft(entry.config);
                          setBaseRevision(read.data!.revision);
                          setDirty(true);
                          setPreview(null);
                        }}
                      >
                        复制为新版本
                      </button>
                      <button
                        disabled={
                          action.busy ||
                          entry.revision === read.data?.active_revision ||
                          entry.revision !== read.data?.revision
                        }
                        onClick={() =>
                          action.run(
                            () =>
                              mutate("/config/activate", {
                                revision: entry.revision,
                                expected_revision: read.data?.revision,
                              }),
                            "应用请求已受理，等待调度器确认",
                          )
                        }
                      >
                        应用此版本
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Freshness
        snapshot={read.snapshot}
        error={read.error || usage.error || submissions.error}
      />
    </>
  );
}
