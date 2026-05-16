"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from "recharts";
import { fetchDORAMetrics, type DORAMetrics } from "@/lib/api";

const fallbackData = [
  { date: "Mon", deployFreq: 0, leadTime: 0, cfr: 0, mttr: 0 },
];

export default function DORAPage() {
  const [metrics, setMetrics] = useState<DORAMetrics | null>(null);
  const [chartData, setChartData] = useState(fallbackData);

  useEffect(() => {
    const load = async () => {
      try {
        const m = await fetchDORAMetrics();
        setMetrics(m);
        // Build a single data point from current metrics
        setChartData([
          {
            date: "Now",
            deployFreq: m.deployment_frequency.value,
            leadTime: m.lead_time_for_changes.value,
            cfr: m.change_failure_rate.value,
            mttr: m.mean_time_to_recovery.value,
          },
        ]);
      } catch {
        // Use fallback
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">DORA Metrics</h2>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartCard title="Deployment Frequency (per day)">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="deployFreq" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Lead Time for Changes (hours)">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="leadTime" stroke="#10b981" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Change Failure Rate (%)">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="cfr" stroke="#f59e0b" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Mean Time to Recovery (minutes)">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="mttr" stroke="#ef4444" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-white p-6">
      <h3 className="text-sm font-semibold text-gray-600 mb-4">{title}</h3>
      {children}
    </div>
  );
}
