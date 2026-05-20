"use client";

import { useEffect, useState, useCallback } from "react";
import { getPerformanceMetrics, PerformanceMetrics, TimelineEntry } from "@/lib/portal-api";

const AGENT_LABELS: Record<string, string> = {
  "plan-collaborate": "Plan & Collaborate",
  "code-build": "Code & Build",
  "test-secure": "Test & Secure",
  "release-deploy": "Release & Deploy",
  "operate-monitor": "Operate & Monitor",
};

const TASK_TYPE_LABELS: Record<string, string> = {
  "code-generation": "Code Generation",
  "code-review": "Code Review",
  "sprint-planning": "Sprint Planning",
  "feature-planning": "Feature Planning",
  "dependency-check": "Dependency Check",
};

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec.toFixed(1)}s`;
  if (sec < 3600) return `${(sec / 60).toFixed(1)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1000000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1000000).toFixed(2)}M`;
}

export default function ObservabilityPage() {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [hours, setHours] = useState(168);
  const [loading, setLoading] = useState(true);

  const loadMetrics = useCallback(async () => {
    try {
      const data = await getPerformanceMetrics(hours);
      setMetrics(data);
    } catch (err) {
      console.error("Failed to load metrics:", err);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    setLoading(true);
    loadMetrics();
    const interval = setInterval(loadMetrics, 15000);
    return () => clearInterval(interval);
  }, [loadMetrics]);

  if (loading && !metrics) {
    return <div className="text-center py-12 text-gray-500">Loading metrics...</div>;
  }

  if (!metrics) {
    return <div className="text-center py-12 text-gray-500">No metrics available</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Observability</h2>
          <p className="text-sm text-gray-500 mt-1">Agent performance, tokens, and cycle times</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="px-3 py-1.5 border rounded-lg text-sm"
          >
            <option value={24}>Last 24h</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
          <button
            onClick={loadMetrics}
            className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Top-level KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KPICard title="Total Tasks" value={String(metrics.total_tasks)} />
        <KPICard
          title="Success Rate"
          value={`${metrics.overall_success_rate}%`}
          color={metrics.overall_success_rate >= 90 ? "green" : metrics.overall_success_rate >= 70 ? "yellow" : "red"}
        />
        <KPICard title="Avg Cycle Time" value={formatDuration(metrics.avg_cycle_time_sec)} />
        <KPICard title="Total Tokens" value={formatTokens(metrics.total_tokens_used)} />
        <KPICard
          title="Failed"
          value={String(metrics.total_failed)}
          color={metrics.total_failed === 0 ? "green" : "red"}
        />
      </div>

      {/* Agent Performance Table */}
      <div className="bg-white rounded-xl border p-6">
        <h3 className="text-lg font-semibold mb-4">Agent Performance</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2 font-medium">Agent</th>
                <th className="pb-2 font-medium text-center">Tasks</th>
                <th className="pb-2 font-medium text-center">Success Rate</th>
                <th className="pb-2 font-medium text-center">Avg Time</th>
                <th className="pb-2 font-medium text-center">P95 Time</th>
                <th className="pb-2 font-medium text-right">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.agents).map(([key, agent]) => (
                <tr key={key} className="border-b last:border-0">
                  <td className="py-3 font-medium">{AGENT_LABELS[key] || key}</td>
                  <td className="py-3 text-center">{agent.total_tasks}</td>
                  <td className="py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      agent.success_rate >= 90 ? "bg-green-100 text-green-700" :
                      agent.success_rate >= 70 ? "bg-yellow-100 text-yellow-700" :
                      "bg-red-100 text-red-700"
                    }`}>
                      {agent.success_rate}%
                    </span>
                  </td>
                  <td className="py-3 text-center">{formatDuration(agent.avg_cycle_time_sec)}</td>
                  <td className="py-3 text-center">{formatDuration(agent.p95_cycle_time_sec)}</td>
                  <td className="py-3 text-right font-mono text-xs">{formatTokens(agent.tokens_used)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Task Type Breakdown */}
      <div className="bg-white rounded-xl border p-6">
        <h3 className="text-lg font-semibold mb-4">Task Type Breakdown</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Object.entries(metrics.task_types).map(([key, tt]) => (
            <div key={key} className="border rounded-lg p-4">
              <h4 className="font-medium text-sm">{TASK_TYPE_LABELS[key] || key}</h4>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-gray-500">Tasks</span>
                  <p className="font-bold">{tt.total}</p>
                </div>
                <div>
                  <span className="text-gray-500">Success</span>
                  <p className="font-bold">{tt.success_rate}%</p>
                </div>
                <div>
                  <span className="text-gray-500">Avg Time</span>
                  <p className="font-bold">{formatDuration(tt.avg_cycle_time_sec)}</p>
                </div>
                <div>
                  <span className="text-gray-500">Tokens</span>
                  <p className="font-bold">{formatTokens(tt.tokens_used)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Task Timeline */}
      <div className="bg-white rounded-xl border p-6">
        <h3 className="text-lg font-semibold mb-4">Recent Tasks</h3>
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {metrics.timeline.slice().reverse().map((entry) => (
            <TimelineRow key={entry.task_id} entry={entry} />
          ))}
          {metrics.timeline.length === 0 && (
            <p className="text-gray-400 text-sm">No tasks in this period</p>
          )}
        </div>
      </div>
    </div>
  );
}

function KPICard({ title, value, color }: { title: string; value: string; color?: string }) {
  const colorClass = color === "green" ? "text-green-600" :
    color === "red" ? "text-red-600" :
    color === "yellow" ? "text-yellow-600" : "text-gray-900";

  return (
    <div className="bg-white rounded-xl border p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{title}</p>
      <p className={`text-2xl font-bold mt-1 ${colorClass}`}>{value}</p>
    </div>
  );
}

const STATUS_DOT: Record<string, string> = {
  completed: "bg-green-500",
  "in-progress": "bg-blue-500 animate-pulse",
  pending: "bg-yellow-500",
  failed: "bg-red-500",
};

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 text-sm">
      <span className={`h-2 w-2 rounded-full ${STATUS_DOT[entry.status] || "bg-gray-300"}`} />
      <span className="text-gray-400 text-xs w-20 shrink-0">
        {new Date(entry.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </span>
      <span className="font-medium w-36 truncate">{AGENT_LABELS[entry.agent_type] || entry.agent_type}</span>
      <span className="text-gray-600 flex-1 truncate">{TASK_TYPE_LABELS[entry.task_type] || entry.task_type}</span>
      {entry.cycle_time_sec !== null && (
        <span className="text-xs text-gray-500 w-16 text-right">{formatDuration(entry.cycle_time_sec)}</span>
      )}
      <span className="text-xs font-mono text-gray-400 w-14 text-right">{formatTokens(entry.tokens_used)}</span>
    </div>
  );
}
