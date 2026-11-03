import { useState } from "react";
import { ArrowRight, BookOpen, FlaskConical } from "lucide-react";
import { useSnapshot } from "../api/client";
import HistoryChart from "../components/HistoryChart";
import {
  Badge,
  Card,
  Empty,
  Heading,
  LinkButton,
  date,
  number,
} from "../components/ui";
import { taskGuides } from "../content/tasks";

export default function Tasks({ params }: { params: URLSearchParams }) {
  const selected = params.get("task");
  const { data } = useSnapshot("/overview");
  const history = useSnapshot(
    `/tasks/history${selected ? `?task=${encodeURIComponent(selected)}` : ""}`,
  );
  return (
    <>
      <Heading
        eyebrow="UNDERSTAND THE BENCHMARKS"
        title="任务介绍"
        description="三个任务优化不同的量子电路；共同目标是在正确性达标后降低官方资源成本。"
        actions={<LinkButton to="/experiments">查看实验</LinkButton>}
      />
      <div className="task-tabs" aria-label="选择任务介绍">
        <a className={!selected ? "active" : ""} href="#/tasks">
          全部任务
        </a>
        {taskGuides.map((task) => (
          <a
            className={selected === task.id ? "active" : ""}
            key={task.id}
            href={`#/tasks?task=${task.id}`}
          >
            {task.name}
          </a>
        ))}
      </div>
      <Card title="先读懂总览里的数字" className="explanation-card">
        <div className="grid three definition-grid">
          <div>
            <strong>单题成本 ↓</strong>
            <p>
              验证器按各题公式计算的资源指标，不是秒数、费用或错误率。三题量级不同，不能用原始数字互相排名。
            </p>
          </div>
          <div>
            <strong>本地组合改善 ↑</strong>
            <p>
              三个“基准成本 ÷ 当前成本”的几何平均。1× 表示没有变化；1.10×
              表示相对指定组合的改善倍数为 1.10。
            </p>
          </div>
          <div>
            <strong>平台成绩 ↑</strong>
            <p>
              Kaggle
              返回的评测分数。它使用官方评分基准；本地相对上次提交的改善倍数不直接等于平台分数。
            </p>
          </div>
        </div>
        <div className="formula">
          组合改善 = ∛[(基准 DQI / 当前 DQI) × (基准 InvSqrt / 当前 InvSqrt) ×
          (基准 DFTHC-SOS / 当前 DFTHC-SOS)]
        </div>
        <p className="muted">
          比较前先确认验证契约与基准。每项正式成本均越低越好，组合改善倍数越高越好。
        </p>
      </Card>
      {taskGuides
        .filter((task) => !selected || task.id === selected)
        .map((task) => {
          const best = data?.best?.find((item: any) => item.task === task.id);
          const taskHistory = history.data?.items?.find(
            (item: any) => item.task === task.id,
          );
          return (
            <Card
              key={task.id}
              className="task-guide"
              title={task.name}
              aside={
                <a href={`#/experiments?task=${task.id}`}>
                  查看该题实验 <ArrowRight size={13} />
                </a>
              }
            >
              <div className="task-guide-heading">
                <div>
                  <p className="eyebrow">{task.subtitle}</p>
                  <p className="lead">{task.summary}</p>
                </div>
                {best && (
                  <div className="task-best">
                    <small>当前本地最佳 · 官方成本</small>
                    <strong>{number(best.official_cost)}</strong>
                    <Badge value={best.validation_status} />
                  </div>
                )}
              </div>
              <div className="formula">{task.formula}</div>
              <p className="muted">{task.symbols}</p>
              <div className="grid two definition-grid">
                <div>
                  <h3>
                    <BookOpen size={16} /> 需要完成什么
                  </h3>
                  <p>{task.contract}</p>
                  <h3>优化目标</h3>
                  <p>{task.objective}</p>
                </div>
                <div>
                  <h3>
                    <FlaskConical size={16} /> 可以研究的方向
                  </h3>
                  <ul className="plain-list">
                    {task.directions.map((direction) => (
                      <li key={direction}>{direction}</li>
                    ))}
                  </ul>
                  <h3>怎样判断有效</h3>
                  <p>{task.validation}</p>
                </div>
              </div>
              <TaskHistory
                key={`${task.id}-${selected === task.id}`}
                history={taskHistory}
                defaultOpen={selected === task.id}
                error={history.error}
              />
              <details className="evidence">
                <summary>本地依据与计量范围</summary>
                <p>{task.source}</p>
                <p>
                  说明依据当前仓库契约整理；上方最佳成本来自实时状态，理论方向不表示已经测得改进。
                </p>
              </details>
            </Card>
          );
        })}
      <Card title="从参数变化到可提交的改进">
        <p>
          先创建独立候选，再完成筛查和官方完整验证。通过验证后仍须比当前已提交组合更好，才能进入提交检查；未通过、未改进或证据不足的实验都保留记录。
        </p>
        <div className="actions">
          <LinkButton to="/workbench">创建实验</LinkButton>
          <LinkButton to="/submissions">查看提交规则与当前原因</LinkButton>
        </div>
      </Card>
    </>
  );
}

function TaskHistory({
  history,
  defaultOpen,
  error,
}: {
  history: any;
  defaultOpen: boolean;
  error?: string;
}) {
  const [improvementsOpen, setImprovementsOpen] = useState(defaultOpen);
  if (!history)
    return (
      <div className="task-history">
        <div className="section-label compact">
          <h3>官方成本趋势</h3>
          <span>{error ? `读取失败：${error}` : "正在读取历史记录…"}</span>
        </div>
      </div>
    );
  const scores = history.score_history || [],
    improvements = history.improvement_history || [];
  return (
    <div className="task-history">
      <div className="section-label compact">
        <h3>官方成本趋势</h3>
        <span>
          {history.pass_count} 个正式 PASS · {history.improvement_count} 次晋级 ·
          成本越低越好
        </span>
      </div>
      <HistoryChart
        title={`${history.task} 官方成本历史`}
        scale="log"
        lowerIsBetter
        points={scores.map((item: any) => ({
          value: item.official_cost,
          label: item.candidate_id,
          at: item.recorded_at,
          emphasized: item.is_promoted,
          current: item.is_current_best,
        }))}
      />
      <details
        className="history-details"
        open={improvementsOpen}
        onToggle={(event) => setImprovementsOpen(event.currentTarget.open)}
      >
        <summary>改进历史（{improvements.length}）</summary>
        {improvements.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>晋级时间（北京时间）</th>
                  <th>候选</th>
                  <th>官方成本 ↓</th>
                  <th>较前最佳降低</th>
                  <th>相对初始基线</th>
                </tr>
              </thead>
              <tbody>
                {[...improvements].reverse().map((item: any) => (
                  <tr key={item.candidate_id}>
                    <td>{date(item.promoted_at)}</td>
                    <td>
                      <a href={`#/experiments?id=${item.candidate_id}`}>
                        {item.candidate_id}
                      </a>
                      {item.is_current_best && <small>当前最佳</small>}
                    </td>
                    <td className="numeric">{number(item.official_cost, 7)}</td>
                    <td className="numeric">{percentage(item.step_reduction)}</td>
                    <td className="numeric">
                      {percentage(item.baseline_reduction)}
                      <small>{factor(item.baseline_factor)}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>暂无已记录的晋级节点</Empty>
        )}
      </details>
      <details className="history-details">
        <summary>全部正式 PASS 分数（{scores.length}）</summary>
        {scores.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>验证时间（北京时间）</th>
                  <th>候选</th>
                  <th>官方成本 ↓</th>
                  <th>记录状态</th>
                </tr>
              </thead>
              <tbody>
                {[...scores].reverse().map((item: any) => (
                  <tr key={item.candidate_id}>
                    <td>{date(item.recorded_at)}</td>
                    <td>
                      <a href={`#/experiments?id=${item.candidate_id}`}>
                        {item.candidate_id}
                      </a>
                    </td>
                    <td className="numeric">{number(item.official_cost, 7)}</td>
                    <td>
                      {item.is_current_best
                        ? "当前最佳"
                        : item.is_promoted
                          ? "曾晋级"
                          : "正式 PASS"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>暂无正式 PASS 分数</Empty>
        )}
      </details>
    </div>
  );
}

const percentage = (value: unknown) =>
  typeof value === "number" ? `${number(value * 100, 5)}%` : "未知";

const factor = (value: unknown) =>
  typeof value === "number" ? `累计 ${number(value, 6)}×` : "累计倍数未知";
