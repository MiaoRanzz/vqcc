import { useState } from "react";
import { ArrowUpRight, Save } from "lucide-react";
import { mutate, useAction, useSnapshot } from "../api/client";
import type { RecordData } from "../api/client";
import {
  Badge,
  Card,
  Empty,
  Evidence,
  Field,
  Freshness,
  Heading,
  Notice,
} from "../components/ui";
const states: Record<string, string> = {
  pending: "待复现",
  running: "实验中",
  supported: "支持",
  rejected: "否定",
  inconclusive: "证据不足",
  unverified: "来源待核实",
  disabled: "已停用",
};
export default function Research() {
  const read = useSnapshot("/research");
  return (
    <>
      <Heading
        eyebrow="RESEARCH / 05"
        title="研究假设"
        description="区分尚未测量的先验与实验结论，让每个方向有据可查。"
      />
      <div className="research-board">
        {Object.entries(states).map(([status, label]) => (
          <section className="research-column" key={status}>
            <div className="column-title">
              <h2>{label}</h2>
              <span>
                {read.data?.items.filter((x: any) => x.status === status)
                  .length ?? 0}
              </span>
            </div>
            {read.data?.items
              .filter((x: any) => x.status === status)
              .sort((a: any, b: any) => a.priority - b.priority)
              .map((item: any) => (
                <ResearchItem
                  key={item.id}
                  item={item}
                  revision={read.data!.revision ?? read.snapshot!.revision}
                />
              ))}
            {!read.data?.items.some((x: any) => x.status === status) && (
              <Empty>暂无假设</Empty>
            )}
          </section>
        ))}
      </div>
      <Card title="来源阅读覆盖">
        <Evidence
          title="主题列表与全文阅读分别统计"
          value={read.data?.coverage}
        />
      </Card>
      <Freshness snapshot={read.snapshot} error={read.error} />
    </>
  );
}
function ResearchItem({
  item,
  revision,
}: {
  item: RecordData;
  revision: number;
}) {
  const [editing, setEditing] = useState(false),
    [status, setStatus] = useState(item.status),
    [priority, setPriority] = useState(item.priority || 0),
    [notes, setNotes] = useState(item.notes || ""),
    [experiments, setExperiments] = useState(
      (item.experiment_ids || []).join(", "),
    ),
    action = useAction();
  return (
    <article className="research-card">
      <div className="research-meta">
        <span>优先级 {item.priority ?? "未记录"}</span>
        <span>{item.id}</span>
      </div>
      <h3>{item.title}</h3>
      <p className="muted">
        未测量先验：
        {typeof item.expected_gain === "object"
          ? JSON.stringify(item.expected_gain)
          : (item.expected_gain ?? "未记录")}
      </p>
      {item.notes && <p>{item.notes}</p>}
      <div className="artifact-links">
        {(item.experiment_ids || []).map((id: string) => (
          <a key={id} href={`#/experiments?id=${id}`}>
            {id}
          </a>
        ))}
      </div>
      <details className="evidence">
        <summary>来源与关联</summary>
        <pre>
          {typeof item.source === "string"
            ? item.source
            : JSON.stringify(item.source, null, 2)}
        </pre>
      </details>
      <div className="actions">
        <button onClick={() => setEditing(!editing)}>
          {editing ? "收起编辑" : "编辑状态与备注"}
        </button>
        <a
          className="button"
          href={`#/workbench?kind=optimize&research=${item.id}&goal=${encodeURIComponent(item.title)}`}
        >
          转为研究任务
          <ArrowUpRight size={13} />
        </a>
      </div>
      {editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action.run(
              () =>
                mutate(`/research/${item.id}/update`, {
                  status,
                  priority,
                  notes,
                  experiment_ids: experiments
                    .split(",")
                    .map((x: string) => x.trim())
                    .filter(Boolean),
                  expected_revision: revision,
                }),
              "研究记录已保存",
            );
          }}
        >
          <Field label="结论状态">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              {Object.entries(states).map(([id, name]) => (
                <option value={id} key={id}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="优先级（越小越靠前）">
            <input
              type="number"
              min={0}
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
            />
          </Field>
          <Field label="备注">
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
          <Field label="关联候选 ID，以英文逗号分隔">
            <input
              value={experiments}
              onChange={(e) => setExperiments(e.target.value)}
            />
          </Field>
          <button className="primary" disabled={action.busy}>
            <Save size={13} /> 保存变更
          </button>
        </form>
      )}
      <Notice error={action.error} success={action.success} />
    </article>
  );
}
