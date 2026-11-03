import { useEffect, useState } from "react";
import { Copy, Download, FlaskConical, RefreshCw } from "lucide-react";
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
  Notice,
  Pager,
  date,
  download,
  number,
  taskNames,
  validationReason,
} from "../components/ui";
export default function Experiments({ params }: { params: URLSearchParams }) {
  const selected = params.get("id"),
    task = params.get("task") || "",
    validation = params.get("validation") || "",
    compareIds = params.get("compare") || "",
    cursor = params.get("cursor") || "0",
    query = params.get("query") || "";
  const [checked, setChecked] = useState<string[]>(
      compareIds.split(",").filter(Boolean),
    ),
    [search, setSearch] = useState(query);
  useEffect(() => setSearch(query), [query]);
  const list = useSnapshot<Page<RecordData>>(
      `/experiments?task=${task}&validation=${validation}&cursor=${cursor || "0"}&query=${encodeURIComponent(params.get("query") || "")}&parent=${encodeURIComponent(params.get("parent") || "")}&generator_revision=${encodeURIComponent(params.get("generator_revision") || "")}${params.has("best") ? "&best=" + params.get("best") : ""}`,
    ),
    detail = useSnapshot(selected ? `/experiments/${selected}` : null),
    compare = useSnapshot(
      compareIds ? `/experiments/compare?ids=${compareIds}` : null,
      false,
    ),
    action = useAction();
  function filter(k: string, v: string) {
    const p = new URLSearchParams(params);
    p.delete("id");
    p.delete("compare");
    p.delete("cursor");
    v ? p.set(k, v) : p.delete(k);
    location.hash = `/experiments?${p}`;
    setChecked([]);
  }
  function setCursor(value: string) {
    const p = new URLSearchParams(params);
    value ? p.set("cursor", value) : p.delete("cursor");
    location.hash = `/experiments?${p}`;
  }
  function showAll() {
    setSearch("");
    setChecked([]);
    location.hash = "/experiments";
  }
  function toggle(id: string) {
    setChecked((values) =>
      values.includes(id)
        ? values.filter((x) => x !== id)
        : values.length < 4
          ? [...values, id]
          : values,
    );
  }
  function start(kind: string) {
    return action.run(
      () =>
        mutate("/jobs", { kind, candidate_id: selected, max_seconds: 3600 }),
      "工作已入队，查看任务页跟踪执行",
    );
  }
  const candidates: RecordData[] = compare.data?.items || [];
  const rows = list.data?.items || [];
  const chosen = list.data?.items.filter((x) => checked.includes(x.id)) || [],
    sameTask = new Set(chosen.map((x) => x.task)).size <= 1;
  function exportCsv() {
    const keys = [
      "id",
      "task",
      "official_cost",
      "validation_status",
      "validation_reason",
      "parameters",
    ];
    download(
      "vqcc-comparison.csv",
      [
        keys,
        ...candidates.map((c) =>
          keys.map((k) =>
            typeof c[k] === "object" ? JSON.stringify(c[k]) : (c[k] ?? ""),
          ),
        ),
      ]
        .map((row) =>
          row.map((x) => `"${String(x).replaceAll('"', '""')}"`).join(","),
        )
        .join("\n"),
      "text/csv;charset=utf-8",
    );
  }
  return (
    <>
      <Heading
        eyebrow="EVIDENCE / 03"
        title="实验与证据"
        description="保留每个候选的参数、验证依据和失败结论。"
        actions={
          <a className="button primary" href="#/workbench">
            <FlaskConical size={16} /> 新建实验
          </a>
        }
      />
      <Notice error={action.error || compare.error} success={action.success} />
      <Card
        title="候选目录"
        aside={<span className="subtle">只比较同题的 2–4 个候选</span>}
      >
        <div className="filters">
          <select
            aria-label="题目"
            value={task}
            onChange={(e) => filter("task", e.target.value)}
          >
            <option value="">全部题目</option>
            {Object.entries(taskNames).map(([id, name]) => (
              <option value={id} key={id}>
                {name}
              </option>
            ))}
          </select>
          <select
            aria-label="验证状态"
            value={validation}
            onChange={(e) => filter("validation", e.target.value)}
          >
            <option value="">全部验证状态</option>
            <option value="PASS">官方 PASS</option>
            <option value="FAIL">官方 FAIL</option>
            <option value="awaiting_validation">待完整验证</option>
            <option value="screen_rejected">初筛无改进</option>
            <option value="generation_failed">生成出错</option>
            <option value="search_stopped">搜索已停止</option>
            <option value="artifact_incomplete">产物不完整</option>
            <option value="analysis_only">仅分析 / 初筛</option>
            <option value="not_generated">尚无验证产物</option>
            <option value="EVIDENCE_STALE">证据需要复核</option>
            <option value="unknown">证据待核实</option>
          </select>
          <input
            aria-label="搜索全部实验"
            placeholder="搜索全部实验：参数、来源、日期、失败原因…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") filter("query", search);
            }}
          />
          <button onClick={() => filter("query", search)}>搜索</button>
          <button onClick={showAll}>显示全部实验</button>
          <button
            disabled={checked.length < 2 || !sameTask}
            onClick={() =>
              (location.hash = `/experiments?compare=${checked.join(",")}`)
            }
          >
            比较已选 {checked.length}/4
          </button>
        </div>
        <details className="evidence">
          <summary>更多筛选条件</summary>
          <div className="filters">
            <input
              aria-label="父候选 ID 筛选"
              key={`parent-${params.get("parent") || ""}`}
              placeholder="父候选 ID，回车应用"
              defaultValue={params.get("parent") || ""}
              onKeyDown={(e) => {
                if (e.key === "Enter") filter("parent", e.currentTarget.value);
              }}
            />
            <input
              aria-label="生成器版本筛选"
              key={`generator-${params.get("generator_revision") || ""}`}
              placeholder="生成器版本指纹，回车应用"
              defaultValue={params.get("generator_revision") || ""}
              onKeyDown={(e) => {
                if (e.key === "Enter")
                  filter("generator_revision", e.currentTarget.value);
              }}
            />
            <select
              aria-label="最佳候选筛选"
              value={params.get("best") || ""}
              onChange={(e) => filter("best", e.target.value)}
            >
              <option value="">全部选择状态</option>
              <option value="true">当前最佳</option>
              <option value="false">非当前最佳</option>
            </select>
          </div>
        </details>
        {!sameTask && (
          <p className="inline-note">
            请选择同一题目的候选；不同题目原始成本不能直接排名。
          </p>
        )}
        {list.loading && !list.data && (
          <div className="loading-state" role="status">
            正在加载实验记录…
          </div>
        )}
        {list.error && (
          <>
            <Notice error={`实验列表读取失败：${list.error}`} />
            <button onClick={() => list.refresh()}>
              <RefreshCw size={14} /> 重试读取实验
            </button>
          </>
        )}
        {list.data && (
          <p className="subtle">
            当前显示 {rows.length} 条
            {list.data.total !== undefined && `，共 ${list.data.total} 条匹配记录`}
          </p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th aria-label="选择" />
                <th>候选与假设</th>
                <th>题目</th>
                <th>官方验证</th>
                <th>正式成本 ↓</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id} className={selected === x.id ? "selected" : ""}>
                  <td>
                    <input
                      aria-label={`选择 ${x.id}`}
                      type="checkbox"
                      checked={checked.includes(x.id)}
                      onChange={() => toggle(x.id)}
                    />
                  </td>
                  <td>
                    <a href={`#/experiments?id=${x.id}`}>{x.id}</a>
                    {x.best && <span className="best-label">当前最佳</span>}
                    <small>{x.hypothesis || "未记录假设"}</small>
                  </td>
                  <td>{taskNames[x.task]}</td>
                  <td>
                    <Badge value={x.validation_status} />
                    {validationReason(x.validation_reason) && (
                      <small>{validationReason(x.validation_reason)}</small>
                    )}
                  </td>
                  <td className="numeric">{number(x.official_cost)}</td>
                  <td>{date(x.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!list.loading && !list.error && list.data && rows.length === 0 && (
          <Empty>当前筛选或分页没有匹配记录，可点击“显示全部实验”。</Empty>
        )}
        <Pager
          cursor={list.data?.next_cursor}
          onNext={setCursor}
          onReset={() => setCursor("")}
        />
      </Card>
      {candidates.length > 0 && (
        <Card
          title="同题比较"
          aside={
            <button onClick={exportCsv}>
              <Download size={14} /> 导出 CSV
            </button>
          }
        >
          <div className="table-wrap">
            <table className="compare-table">
              <thead>
                <tr>
                  <th>指标</th>
                  {candidates.map((c) => (
                    <th key={c.id}>
                      <a href={`#/experiments?id=${c.id}`}>{c.id}</a>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>官方成本 ↓</th>
                  {candidates.map((c) => (
                    <td key={c.id}>{number(c.official_cost)}</td>
                  ))}
                </tr>
                <tr>
                  <th>正式验证</th>
                  {candidates.map((c) => (
                    <td key={c.id}>
                      <Badge value={c.validation_status} />
                      {validationReason(c.validation_reason) && (
                        <small>{validationReason(c.validation_reason)}</small>
                      )}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th>误差 / 容差</th>
                  {candidates.map((c) => (
                    <td key={c.id}>
                      {number(c.metrics?.worst_error_over_tolerance, 7)}
                    </td>
                  ))}
                </tr>
                {Array.from(
                  new Set(
                    candidates.flatMap((c) => Object.keys(c.parameters || {})),
                  ),
                ).map((key) => (
                  <tr
                    key={key}
                    className={
                      new Set(candidates.map((c) => c.parameters?.[key])).size >
                      1
                        ? "diff-row"
                        : ""
                    }
                  >
                    <th>{key}</th>
                    {candidates.map((c) => (
                      <td key={c.id}>{c.parameters?.[key] ?? "未记录"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            浅色行突出参数差异。
            {compare.data?.comparable_environment
              ? "已记录的验证环境一致。"
              : "环境证据不同或不完整，成本不可直接归因于参数变化。"}
          </p>
          <Evidence title="验证环境与完整比较依据" value={compare.data} />
        </Card>
      )}
      {selected && detail.data && (
        <Card
          title={`${taskNames[detail.data.task]} · 候选详情`}
          aside={<Badge value={detail.data.validation_status} />}
        >
          <p className="lead">{detail.data.hypothesis || "没有记录研究假设"}</p>
          {validationReason(detail.data.validation_reason) && (
            <p className="inline-note">
              状态依据：{validationReason(detail.data.validation_reason)}
            </p>
          )}
          <div className="actions">
            <a className="button" href={`#/workbench?parent=${selected}`}>
              <Copy size={14} /> 复制为新实验
            </a>
            <button
              disabled={action.busy}
              onClick={() => start("local_validate")}
            >
              加入完整验证队列
            </button>
            <button
              disabled={action.busy}
              onClick={() => start("local_promote")}
            >
              请求晋级
            </button>
            <button
              onClick={() =>
                download(
                  `${selected}-summary.json`,
                  JSON.stringify(detail.data, null, 2),
                )
              }
            >
              <Download size={14} /> 导出摘要
            </button>
          </div>
          <p className="muted">
            本地验证与晋级不调用模型；晋级仍由流水线判断完整证据和成本改进。
          </p>
          <div className="grid two">
            <div>
              <h3>参数与谱系</h3>
              <KeyValues value={detail.data.parameters} />
              <p>
                父候选：
                {detail.data.parent ? (
                  <a href={`#/experiments?id=${detail.data.parent}`}>
                    {detail.data.parent}
                  </a>
                ) : (
                  "未记录"
                )}
              </p>
              <div className="lineage">
                {detail.data.lineage?.map((c: any) => (
                  <a key={c.id} href={`#/experiments?id=${c.id}`}>
                    {c.id}
                  </a>
                ))}
              </div>
            </div>
            <div>
              <h3>官方测量</h3>
              <KeyValues
                value={{
                  官方成本: number(detail.data.official_cost),
                  筛选成本下界: number(detail.data.screening_cost),
                  ...detail.data.metrics,
                }}
              />
            </div>
          </div>
          <Evidence title="生成与初筛" value={detail.data.generation} />
          <Evidence title="完整官方验证证据" value={detail.data.verification} />
          <Evidence
            title="额外诊断（不替代正式验证）"
            value={detail.data.diagnostics}
          />
          <Evidence
            title="源码、环境与复现"
            value={{
              source: detail.data.source,
              reproduction: detail.data.reproduction,
            }}
          />
          {detail.data.artifacts?.length > 0 && (
            <div className="artifact-links">
              {detail.data.artifacts.map((a: any) => (
                <a
                  key={a.id}
                  href={`/api/v1/artifacts/${a.id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {a.name} ↗
                </a>
              ))}
            </div>
          )}
        </Card>
      )}
      <Freshness snapshot={list.snapshot} error={list.error || detail.error} />
    </>
  );
}
