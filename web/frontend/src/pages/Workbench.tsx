import { useEffect, useState } from "react";
import { ArrowRight, Cpu, Sparkles } from "lucide-react";
import { mutate, useAction, useSnapshot } from "../api/client";
import type { RecordData } from "../api/client";
import {
  Card,
  Evidence,
  Field,
  Freshness,
  Heading,
  KeyValues,
  Notice,
  duration,
  reason,
  taskNames,
} from "../components/ui";
export default function Workbench({ params }: { params: URLSearchParams }) {
  const parent = params.get("parent"),
    research = params.get("research"),
    schema = useSnapshot("/parameter-schemas", false),
    config = useSnapshot("/config"),
    source = useSnapshot(parent ? `/experiments/${parent}` : null, false);
  const [kind, setKind] = useState(
      research || params.get("kind") === "optimize"
        ? "optimize"
        : "local_experiment",
    ),
    [task, setTask] = useState("invsqrt"),
    [optimizationTask, setOptimizationTask] = useState("auto"),
    [parameters, setParameters] = useState<RecordData>({}),
    [hypothesis, setHypothesis] = useState(params.get("goal") || ""),
    [seconds, setSeconds] = useState(1800),
    [optimizationSeconds, setOptimizationSeconds] = useState(3600),
    [dataset, setDataset] = useState(""),
    [model, setModel] = useState(""),
    [reasoning, setReasoning] = useState(""),
    [tier, setTier] = useState(""),
    [subagents, setSubagents] = useState(false),
    [preview, setPreview] = useState<RecordData | null>(null),
    [submitted, setSubmitted] = useState("");
  const [ready, setReady] = useState(false);
  const selectedTask = kind === "optimize" ? optimizationTask : task,
    maxSeconds = kind === "optimize" ? optimizationSeconds : seconds;
  const action = useAction(),
    fields = schema.data?.tasks?.[task]?.fields || {};
  const selectedParent = source.data?.task === task ? parent : null;
  const uncopiedParameters = selectedParent
    ? Object.keys(source.data?.parameters || {}).filter(
        (key) => !(key in fields),
      )
    : [];
  const best = useSnapshot("/overview", false);
  function defaults(t: string) {
    return Object.fromEntries(
      Object.entries(schema.data?.tasks?.[t]?.fields || {}).map(
        ([key, field]) => [key, (field as RecordData).default],
      ),
    );
  }
  useEffect(() => {
    if (ready || !schema.data || !config.data || (parent && !source.data))
      return;
    const selectedTask = source.data?.task || task;
    setTask(selectedTask);
    setParameters(
      Object.fromEntries(
        Object.entries(defaults(selectedTask)).map(([key, value]) => [
          key,
          source.data?.parameters?.[key] ?? value,
        ]),
      ),
    );
    if (source.data) setHypothesis(source.data.hypothesis || "");
    setDataset(schema.data.datasets?.[0]?.id || "");
    const c = config.data.config;
    setModel(c.model || "");
    setReasoning(c.reasoning || "");
    setTier(c.service_tier || "");
    setReady(true);
  }, [ready, schema.data, config.data, source.data, parent]);
  function changeTask(value: string) {
    setTask(value);
    setParameters(defaults(value));
  }
  const payload = {
    kind,
    task: selectedTask === "auto" ? null : selectedTask,
    ...(kind === "local_experiment"
      ? {
          generator_revision: schema.data?.generator_revision,
          parent_candidate_id: selectedParent || undefined,
          parameters,
          dataset_id: dataset || undefined,
          validate: true,
        }
      : {
          model,
          reasoning,
          service_tier: tier,
          research_id: research || undefined,
          allow_subagents: subagents,
        }),
    hypothesis,
    max_seconds: maxSeconds,
  };
  const signature = JSON.stringify(payload);
  useEffect(() => {
    setPreview(null);
    setSubmitted("");
  }, [signature]);
  async function loadBest() {
    const id = best.data?.best?.find((x: any) => x.task === task)?.id;
    if (id) location.hash = `/workbench?parent=${id}`;
  }
  return (
    <>
      <Heading
        eyebrow="CREATE / 04"
        title="启动工作台"
        description="从一个明确的假设开始，每次创建独立的工作记录。"
      />
      <div className="mode-tabs">
        <button
          className={kind === "local_experiment" ? "active" : ""}
          onClick={() => {
            setKind("local_experiment");
            setPreview(null);
          }}
        >
          <Cpu size={22} />
          <div>
            <strong>本地实验</strong>
            <span>使用本机算力，不调用 Codex</span>
          </div>
        </button>
        <button
          className={kind === "optimize" ? "active" : ""}
          onClick={() => {
            setKind("optimize");
            setPreview(null);
          }}
        >
          <Sparkles size={22} />
          <div>
            <strong>Codex 优化</strong>
            <span>消耗现有 Codex 使用额度</span>
          </div>
        </button>
      </div>
      <Notice
        error={action.error}
        success={submitted ? `任务 ${submitted} 已入队` : undefined}
      />
      {submitted && (
        <a className="button primary" href={`#/jobs?id=${submitted}`}>
          查看队列中的任务 <ArrowRight size={15} />
        </a>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action.run(async () => {
            const result: any = await mutate("/jobs/preview", payload);
            setPreview(result.data || result);
          }, "");
        }}
        onChange={() => {
          setPreview(null);
          setSubmitted("");
        }}
      >
        <fieldset disabled={!ready}>
          <Card
            title="工作设置"
            aside={
              <span className="subtle">
                配置 v{config.data?.active_revision ?? "…"}
              </span>
            }
          >
            <div className="form-grid">
              <Field label="目标题目">
                <select
                  value={selectedTask}
                  onChange={(e) =>
                    kind === "optimize"
                      ? setOptimizationTask(e.target.value)
                      : changeTask(e.target.value)
                  }
                >
                  {kind === "optimize" && (
                    <option value="auto">全部三个任务</option>
                  )}
                  {Object.entries(taskNames).map(([id, name]) => (
                    <option value={id} key={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="最长运行时间（秒）"
                hint="到时由统一监督器停止；与其他任务共用机器预算。"
              >
                <input
                  type="number"
                  min="30"
                  max={config.data?.config?.max_agent_seconds || 19800}
                  value={maxSeconds}
                  required
                  onChange={(e) =>
                    kind === "optimize"
                      ? setOptimizationSeconds(Number(e.target.value))
                      : setSeconds(Number(e.target.value))
                  }
                />
              </Field>
            </div>
            <Field
              label={
                kind === "local_experiment" ? "实验假设与说明" : "研究目标"
              }
            >
              <textarea
                rows={3}
                required
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
                placeholder="说明要改变什么，以及预期如何降低官方成本。"
              />
            </Field>
            {kind === "local_experiment" ? (
              <>
                <div className="section-label">
                  <h3>生成器参数</h3>
                  <div className="actions">
                    <button
                      type="button"
                      onClick={() => setParameters(defaults(task))}
                    >
                      加载参考默认
                    </button>
                    <button type="button" onClick={loadBest}>
                      复制当前最佳
                    </button>
                  </div>
                </div>
                {selectedParent && (
                  <p className="inline-note">
                    父候选：
                    <a href={`#/experiments?id=${selectedParent}`}>
                      {selectedParent}
                    </a>
                    。将创建新候选，不覆盖原参数。
                  </p>
                )}
                {uncopiedParameters.length > 0 && (
                  <p className="inline-note">
                    未复制的参数：{uncopiedParameters.join("、")}
                    。当前生成器表单只支持下列参数；
                    这次新实验不会复现父候选的自定义参数。可点击父候选查看原参数。
                  </p>
                )}
                <div className="form-grid">
                  {Object.entries(fields).map(([key, v]) => {
                    const field = v as RecordData;
                    return (
                      <Field
                        key={key}
                        label={field.label || key}
                        hint={`${field.minimum}–${field.maximum} · 参考默认 ${field.default}`}
                      >
                        <input
                          type="number"
                          required
                          min={field.minimum}
                          max={field.maximum}
                          step={1}
                          value={parameters[key] ?? field.default}
                          onChange={(e) =>
                            setParameters({
                              ...parameters,
                              [key]: Number(e.target.value),
                            })
                          }
                        />
                      </Field>
                    );
                  })}
                </div>
                {task === "dfthcsos" && schema.data?.datasets?.length > 0 && (
                  <Field label="来源数据集">
                    <select
                      value={dataset}
                      onChange={(e) => setDataset(e.target.value)}
                    >
                      {schema.data?.datasets.map((d: any) => (
                        <option key={d.id} value={d.id}>
                          {d.name || d.id}
                        </option>
                      ))}
                    </select>
                  </Field>
                )}
                <div className="notice info">
                  生成成功后自动进行完整官方验证。所有可行优化均须验证。
                </div>
                <p className="muted">
                  完整验证通过后，晋级仍需单独发起。参考默认参数不等于当前最佳。
                </p>
              </>
            ) : (
              <>
                <div className="notice info">
                  本次属于顶层模型任务，启动前预留每日次数；启动后的失败、超时或取消仍占用一次。
                </div>
                <div className="form-grid">
                  <Field label="模型">
                    <input
                      required
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="使用项目已配置模型"
                    />
                  </Field>
                  <Field label="推理强度">
                    <input
                      required
                      value={reasoning}
                      onChange={(e) => setReasoning(e.target.value)}
                    />
                  </Field>
                  <Field label="服务档位">
                    <input
                      required
                      value={tier}
                      onChange={(e) => setTier(e.target.value)}
                    />
                  </Field>
                </div>
                <p className="muted">
                  支持信息：
                  {schema.data?.model_support?.message ||
                    "以本机 CLI 与账户支持为准，尚未确认的选项不会自动替换。"}
                </p>
                <details className="evidence">
                  <summary>资源与子代理</summary>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={subagents}
                      onChange={(e) => setSubagents(e.target.checked)}
                    />{" "}
                    允许子代理，共用本次顶层任务预算
                  </label>
                  <KeyValues
                    value={{
                      "CPU 上限": config.data?.config?.cpu_limit,
                      "RSS 提前停止 GiB": config.data?.config?.memory_stop_gib,
                      GPU: config.data?.config?.gpu_ids,
                      子代理: subagents ? "允许，共用顶层任务预算" : "未启用",
                    }}
                  />
                  <p>
                    次数不是 token 或费用硬上限；子代理不会获得独立额外额度。
                  </p>
                </details>
              </>
            )}
            <div className="form-footer">
              <span>
                生成器版本{" "}
                {String(schema.data?.generator_revision || "未记录").slice(
                  0,
                  12,
                )}
              </span>
              <button
                type="submit"
                className="primary"
                disabled={action.busy || !schema.data}
              >
                预检工作 <ArrowRight size={16} />
              </button>
            </div>
          </Card>
        </fieldset>
      </form>
      {preview && (
        <Card title="确认并加入队列" className="confirmation">
          <KeyValues
            value={{
              工作类型:
                kind === "local_experiment"
                  ? "本地实验 · 不调用模型"
                  : "Codex 优化 · 消耗模型额度",
              父候选: preview.request?.parent_candidate_id || parent || "无",
              配置版本: preview.config_revision || config.data?.active_revision,
              最长运行: duration(maxSeconds),
              等待原因:
                reason(preview.blocked_reason || preview.waiting_reason) ||
                "由调度器在启动时重新检查",
            }}
          />
          <Evidence title="参数、预算与预检依据" value={preview} />
          <button
            className="primary"
            disabled={action.busy}
            onClick={() =>
              action.run(async () => {
                const result: any = await mutate(
                  "/jobs",
                  kind === "local_experiment"
                    ? {
                        ...payload,
                        parent_candidate_id:
                          preview.request?.parent_candidate_id,
                        generator_revision: preview.request?.generator_revision,
                      }
                    : payload,
                );
                const data = result.data || result;
                setSubmitted(data.job_id);
                setPreview(null);
              }, "")
            }
          >
            确认加入队列
          </button>
        </Card>
      )}
      <Freshness
        snapshot={schema.snapshot}
        error={schema.error || config.error || source.error}
      />
    </>
  );
}
