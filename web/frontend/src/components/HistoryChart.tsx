import { number } from "./ui";

export interface HistoryPoint {
  value: number;
  label: string;
  at?: string | null;
  emphasized?: boolean;
  current?: boolean;
}

export default function HistoryChart({
  title,
  points,
  scale = "linear",
  lowerIsBetter = false,
}: {
  title: string;
  points: HistoryPoint[];
  scale?: "linear" | "log";
  lowerIsBetter?: boolean;
}) {
  const usable = points.filter(
    (point) =>
      Number.isFinite(point.value) && (scale !== "log" || point.value > 0),
  );
  if (!usable.length)
    return <div className="history-chart-empty">暂无可绘制的历史分数</div>;

  const width = 760,
    height = 230,
    left = 72,
    right = 22,
    top = 22,
    bottom = 42,
    plotWidth = width - left - right,
    plotHeight = height - top - bottom,
    transformed = usable.map((point) =>
      scale === "log" ? Math.log10(point.value) : point.value,
    ),
    minimum = Math.min(...transformed),
    maximum = Math.max(...transformed),
    range = maximum - minimum || 1,
    timestamps = usable.map((point) =>
      point.at ? Date.parse(point.at) : Number.NaN,
    ),
    validTimes = timestamps.filter(Number.isFinite),
    firstTime = validTimes.length ? Math.min(...validTimes) : 0,
    lastTime = validTimes.length ? Math.max(...validTimes) : 0,
    useTime = validTimes.length === usable.length && lastTime > firstTime,
    coordinates = usable.map((point, index) => ({
      point,
      x:
        left +
        (useTime
          ? ((timestamps[index] - firstTime) / (lastTime - firstTime)) *
            plotWidth
          : (index / Math.max(1, usable.length - 1)) * plotWidth),
      y: top + ((maximum - transformed[index]) / range) * plotHeight,
    })),
    line = coordinates.map(({ x, y }) => `${x},${y}`).join(" "),
    start = usable[0],
    end = usable[usable.length - 1];

  return (
    <div className="history-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}，${usable.length} 个历史点，${lowerIsBetter ? "越低越好" : "越高越好"}`}
      >
        <line x1={left} y1={top} x2={left} y2={top + plotHeight} />
        <line
          x1={left}
          y1={top + plotHeight}
          x2={left + plotWidth}
          y2={top + plotHeight}
        />
        {[0, 0.5, 1].map((position) => {
          const y = top + position * plotHeight,
            transformedValue = maximum - position * range,
            value =
              scale === "log"
                ? Math.pow(10, transformedValue)
                : transformedValue;
          return (
            <g key={position}>
              <line
                className="history-grid-line"
                x1={left}
                y1={y}
                x2={left + plotWidth}
                y2={y}
              />
              <text x={left - 10} y={y + 4} textAnchor="end">
                {number(value, 4)}
              </text>
            </g>
          );
        })}
        {coordinates.length > 1 && <polyline points={line} />}
        {coordinates.map(({ point, x, y }, index) => (
          <circle
            key={`${point.label}-${index}`}
            cx={x}
            cy={y}
            r={point.current ? 6 : point.emphasized ? 4.5 : 3}
            className={`${point.emphasized ? "promoted" : ""} ${point.current ? "current" : ""}`}
          >
            <title>
              {point.label}：{number(point.value, 7)}
            </title>
          </circle>
        ))}
        <text x={left} y={height - 12} textAnchor="start">
          {formatDay(start.at)}
        </text>
        <text x={left + plotWidth} y={height - 12} textAnchor="end">
          {formatDay(end.at)}
        </text>
      </svg>
      <div className="history-chart-legend">
        <span>
          <i /> 全部记录
        </span>
        {usable.some((point) => point.emphasized) && (
          <span>
            <i className="promoted" /> 晋级节点
          </span>
        )}
        <span>
          <i className="current" /> 当前值
        </span>
        <span>{scale === "log" ? "纵轴为对数刻度" : "纵轴为线性刻度"}</span>
      </div>
    </div>
  );
}

function formatDay(value?: string | null) {
  if (!value) return "时间未记录";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
  });
}
