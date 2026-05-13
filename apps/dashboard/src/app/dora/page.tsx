"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from "recharts";

const mockData = [
  { date: "Mon", deployFreq: 10, leadTime: 2.5, cfr: 4, mttr: 20 },
  { date: "Tue", deployFreq: 14, leadTime: 2.1, cfr: 3, mttr: 18 },
  { date: "Wed", deployFreq: 12, leadTime: 2.3, cfr: 5, mttr: 22 },
  { date: "Thu", deployFreq: 16, leadTime: 1.8, cfr: 2, mttr: 15 },
  { date: "Fri", deployFreq: 11, leadTime: 2.6, cfr: 3, mttr: 19 },
];

export default function DORAPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">DORA Metrics</h2>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartCard title="Deployment Frequency (per day)">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={mockData}>
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
            <LineChart data={mockData}>
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
            <LineChart data={mockData}>
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
            <LineChart data={mockData}>
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
