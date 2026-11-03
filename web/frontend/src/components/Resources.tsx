import { Cpu, HardDrive, MemoryStick, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import type { RecordData } from "../api/client";
import { Card, date, number } from "./ui";

export default function Resources({ resources }: { resources: RecordData }) {
  const host = resources.host || {},
    task = resources.task || {},
    cpu = host.cpu || {},
    memory = host.memory || {},
    disk = host.disk || {},
    gpu = host.gpu || {};
  return (
    <Card
      title="服务器资源与任务占用"
      aside={
        <span className="subtle">整机采样于 {date(host.observed_at)}</span>
      }
    >
      <p className="resource-scope">
        整机观测包含服务器上的其他项目。下方单独列出本项目任务的占用和预算。
      </p>
      <div className="resource-list host-resources">
        <Resource
          icon={<Cpu size={19} />}
          label="服务器 CPU"
          value={
            cpu.status === "observed"
              ? `${number(cpu.cores)} / ${number(cpu.total_cores, 0)} 核`
              : cpu.status === "warming_up"
                ? "正在建立采样"
                : "暂不可用"
          }
          detail={
            cpu.reason ||
            (cpu.status === "observed"
              ? `整机利用率 ${number(cpu.percent)}% · 非本项目单独占用`
              : "等待连续采样后计算 CPU 使用量")
          }
        />
        <Resource
          icon={<MemoryStick size={19} />}
          label="服务器内存"
          value={
            memory.status === "observed"
              ? `${number(memory.used_gib)} / ${number(memory.total_gib)} GiB`
              : "暂不可用"
          }
          detail={
            memory.reason ||
            `可用 ${number(memory.available_gib)} GiB · 整机口径`
          }
        />
        <Resource
          icon={<HardDrive size={19} />}
          label="数据盘可用空间"
          value={
            disk.status === "observed"
              ? `${number(disk.free_gib)} GiB`
              : "暂不可用"
          }
          detail={
            disk.reason ||
            `容量 ${number(disk.total_gib)} GiB · 数据目录所在磁盘`
          }
        />
      </div>
      <div className="gpu-samples">
        <div className="resource-label">
          <Sparkles size={17} />
          <strong>GPU 设备观测</strong>
          <span>设备级，可能包含其他项目</span>
        </div>
        {gpu.status === "available" ? (
          <div className="gpu-devices">
            {(gpu.devices || []).map((device: RecordData) => (
              <div key={device.index}>
                <strong>
                  GPU {device.index} · {device.name}
                </strong>
                <span>
                  利用率 {number(device.utilization_percent)}% · 显存{" "}
                  {number(device.memory_used_gib)} /{" "}
                  {number(device.memory_total_gib)} GiB
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">
            {gpu.status === "unallocated"
              ? "本项目没有分配 GPU。"
              : gpu.reason || "GPU 监控暂不可用，未将缺失值记为 0%。"}
          </p>
        )}
      </div>
      <div className="task-resource-summary">
        <div>
          <strong>本项目当前任务</strong>
          <p>
            {task.reason ||
              (task.status === "idle"
                ? "当前没有运行任务，因此没有任务 CPU / RSS 样本。"
                : task.status === "observed"
                  ? "以下数值只统计受监督任务进程树。"
                  : "没有可归属到当前任务的有效样本。")}
          </p>
        </div>
        {task.status === "observed" && (
          <div className="task-resource-values">
            <span>
              CPU <strong>{number(task.cpu_cores)} 核</strong>
            </span>
            <span>
              RSS <strong>{number(task.rss_gib)} GiB</strong>
            </span>
            <small>采样于 {date(task.observed_at)}</small>
          </div>
        )}
      </div>
      <p className="resource-budget">
        项目预算：最多 {resources.cpu_limit ?? "未知"} 核；进程树 RSS 达到{" "}
        {resources.memory_stop_gib ?? "未知"} GiB 时提前停止。RSS
        可能重复计算共享页，与整机内存使用量的口径不同。
      </p>
    </Card>
  );
}
function Resource({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="resource">
      <div>
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
