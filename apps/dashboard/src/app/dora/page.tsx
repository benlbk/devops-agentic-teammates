"use client";

import { useEffect, useState } from "react";
import { fetchDORAMetrics, type DORAMetrics, type DORAMetricItem } from "@/lib/api";

const LEVEL_COLORS: Record<string, string> = {
  elite: "bg-green-100 text-green-800 border-green-300",
  high: "bg-blue-100 text-blue-800 border-blue-300",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
  low: "bg-red-100 text-red-800 border-red-300",
};

const LEVEL_LABELS: Record<string, string> = {
  elite: "Elite",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const METRIC_CONFIG = [
  {
    key: "deployment_frequency" as const,
    title: "Deployment Frequency",
    icon: "🚀",
    description: "How often code is deployed to production",
    benchmarks: "Elite: multiple/day · High: weekly · Medium: monthly · Low: <monthly",
    format: (v: number) => (v >= 1 ? `${v.toFixed(1)}/day` : v > 0 ? `${(v * 7).toFixed(1)}/week` : "No deploys"),
  },
  {
    key: "lead_time_for_changes" as const,
    title: "Lead Time for Changes",
    icon: "⏱️",
    description: "Time from commit to production deploy",
    benchmarks: "Elite: <1h · High: <1 day · Medium: <1 week · Low: >1 week",
    format: (v: number) => (v === 0 ? "No data" : v < 1 ? `${Math.round(v * 60)}m` : `${v.toFixed(1)}h`),
  },
  {
    key: "change_failure_rate" as const,
    title: "Change Failure Rate",
    icon: "💥",
    description: "Percentage of deployments causing failure",
    benchmarks: "Elite: ≤5% · High: ≤10% · Medium: ≤15% · Low: >15%",
    format: (v: number) => `${v.toFixed(1)}%`,
  },
  {
    key: "mean_time_to_recovery" as const,
    title: "Mean Time to Recovery",
    icon: "🔧",
    description: "Time to restore service after failure",
    benchmarks: "Elite: <1h · High: <1 day · Medium: <1 week · Low: >1 week",
    format: (v: number) => (v === 0 ? "No incidents" : v < 60 ? `${Math.round(v)}m` : `${(v / 60).toFixed(1)}h`),
  },
];

export default function DORAPage() {
  const [metrics, setMetrics] = useState<DORAMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const m = await fetchDORAMetrics();
        setMetrics(m);
        setLastUpdated(new Date());
      } catch {
        // Keep previous data
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  const overallLevel = metrics
    ? getOverallLevel([
        metrics.deployment_frequency,
        metrics.lead_time_for_changes,
        metrics.change_failure_rate,
        metrics.mean_time_to_recovery,
      ])
    : "low";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">DORA Metrics</h2>
          <p className="text-sm text-gray-500 mt-1">
            Software delivery performance based on{" "}
            <a href="https://dora.dev" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
              DORA research
            </a>
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-400">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <span className={`px-3 py-1 rounded-full text-sm font-medium border ${LEVEL_COLORS[overallLevel]}`}>
            Overall: {LEVEL_LABELS[overallLevel]}
          </span>
        </div>
      </div>

      {loading && !metrics ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-lg border bg-white p-6 animate-pulse h-48" />
          ))}
        </div>
      ) : metrics ? (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {METRIC_CONFIG.map((config) => {
              const metric = metrics[config.key];
              return (
                <MetricCard key={config.key} config={config} metric={metric} />
              );
            })}
          </div>

          <div className="rounded-lg border bg-white p-6">
            <h3 className="text-sm font-semibold text-gray-600 mb-4">Performance Level Guide</h3>
            <div className="grid grid-cols-4 gap-4 text-center text-sm">
              {(["elite", "high", "medium", "low"] as const).map((level) => (
                <div key={level} className={`rounded-lg border p-3 ${LEVEL_COLORS[level]}`}>
                  <div className="font-bold">{LEVEL_LABELS[level]}</div>
                  <div className="text-xs mt-1 opacity-75">
                    {level === "elite" && "Top performers"}
                    {level === "high" && "Above average"}
                    {level === "medium" && "Average"}
                    {level === "low" && "Needs improvement"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-lg border bg-white p-12 text-center text-gray-500">
          Failed to load DORA metrics
        </div>
      )}
    </div>
  );
}

function MetricCard({
  config,
  metric,
}: {
  config: (typeof METRIC_CONFIG)[number];
  metric: DORAMetricItem;
}) {
  const level = metric.level || "low";
  return (
    <div className="rounded-lg border bg-white p-6 space-y-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{config.icon}</span>
          <div>
            <h3 className="text-sm font-semibold text-gray-900">{config.title}</h3>
            <p className="text-xs text-gray-500">{config.description}</p>
          </div>
        </div>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${LEVEL_COLORS[level]}`}>
          {LEVEL_LABELS[level]}
        </span>
      </div>

      <div className="text-3xl font-bold text-gray-900">
        {config.format(metric.value)}
      </div>

      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{config.benchmarks}</span>
      </div>

      {(metric.total_7d !== undefined || metric.sample_size !== undefined || metric.total !== undefined) && (
        <div className="pt-2 border-t text-xs text-gray-500 flex gap-4">
          {metric.total_7d !== undefined && <span>{metric.total_7d} deploys (7d)</span>}
          {metric.sample_size !== undefined && <span>{metric.sample_size} samples</span>}
          {metric.total !== undefined && (
            <span>{metric.failed}/{metric.total} failed</span>
          )}
        </div>
      )}
    </div>
  );
}

function getOverallLevel(items: DORAMetricItem[]): string {
  const levels = items.map((i) => i.level || "low");
  const scores = levels.map((l) => ({ elite: 4, high: 3, medium: 2, low: 1 })[l] || 1);
  const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
  if (avg >= 3.5) return "elite";
  if (avg >= 2.5) return "high";
  if (avg >= 1.5) return "medium";
  return "low";
}
