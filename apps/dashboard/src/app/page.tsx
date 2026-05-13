export default function DashboardHome() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Overview</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard title="Deployment Frequency" value="12/day" trend="+15%" />
        <MetricCard title="Lead Time" value="2.3h" trend="-8%" />
        <MetricCard title="Change Failure Rate" value="3.2%" trend="-12%" />
        <MetricCard title="MTTR" value="18min" trend="-25%" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border bg-white p-6">
          <h3 className="text-lg font-semibold mb-4">Agent Activity (24h)</h3>
          <div className="space-y-3">
            <AgentRow name="Plan & Collaborate" tasks={8} status="idle" />
            <AgentRow name="Code & Build" tasks={24} status="active" />
            <AgentRow name="Test & Secure" tasks={19} status="active" />
            <AgentRow name="Release & Deploy" tasks={6} status="idle" />
            <AgentRow name="Operate & Monitor" tasks={42} status="active" />
          </div>
        </div>
        <div className="rounded-lg border bg-white p-6">
          <h3 className="text-lg font-semibold mb-4">Recent Events</h3>
          <div className="space-y-2 text-sm">
            <EventRow time="2m ago" message="PR #142 auto-reviewed — APPROVED" />
            <EventRow time="15m ago" message="Canary deploy v1.8.3 → production (100%)" />
            <EventRow time="32m ago" message="Security scan passed — 0 findings" />
            <EventRow time="1h ago" message="Ephemeral env pr-138 destroyed" />
            <EventRow time="2h ago" message="Cost alert: EKS spend +12% vs forecast" />
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ title, value, trend }: { title: string; value: string; trend: string }) {
  const isPositive = trend.startsWith("-");
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-gray-500">{title}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      <p className={`text-xs mt-1 ${isPositive ? "text-green-600" : "text-red-600"}`}>{trend}</p>
    </div>
  );
}

function AgentRow({ name, tasks, status }: { name: string; tasks: number; status: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${status === "active" ? "bg-green-500" : "bg-gray-300"}`} />
        <span className="text-sm font-medium">{name}</span>
      </div>
      <span className="text-sm text-gray-500">{tasks} tasks</span>
    </div>
  );
}

function EventRow({ time, message }: { time: string; message: string }) {
  return (
    <div className="flex gap-3 py-1">
      <span className="text-gray-400 whitespace-nowrap">{time}</span>
      <span>{message}</span>
    </div>
  );
}
