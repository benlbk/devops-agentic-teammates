export default function AgentsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Agent Activity</h2>

      <div className="space-y-4">
        {agents.map((agent) => (
          <div key={agent.name} className="rounded-lg border bg-white p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">{agent.name}</h3>
                <p className="text-sm text-gray-500">{agent.description}</p>
              </div>
              <span
                className={`px-3 py-1 rounded-full text-xs font-medium ${
                  agent.status === "active"
                    ? "bg-green-100 text-green-800"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {agent.status}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-4 text-center">
              <Stat label="Tasks Today" value={agent.tasksToday} />
              <Stat label="Success Rate" value={`${agent.successRate}%`} />
              <Stat label="Avg Duration" value={agent.avgDuration} />
              <Stat label="Tokens Used" value={agent.tokensUsed} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-bold">{value}</p>
    </div>
  );
}

const agents = [
  { name: "Plan & Collaborate", description: "Transforms designs into actionable plans", status: "idle", tasksToday: 8, successRate: 100, avgDuration: "45s", tokensUsed: "12.4K" },
  { name: "Code & Build", description: "Generates code, reviews PRs, manages builds", status: "active", tasksToday: 24, successRate: 96, avgDuration: "32s", tokensUsed: "89.2K" },
  { name: "Test & Secure", description: "Generates tests, runs security scans", status: "active", tasksToday: 19, successRate: 100, avgDuration: "28s", tokensUsed: "45.1K" },
  { name: "Release & Deploy", description: "Manages releases and deployments", status: "idle", tasksToday: 6, successRate: 100, avgDuration: "2m", tokensUsed: "8.3K" },
  { name: "Operate & Monitor", description: "Monitors, self-heals, optimizes", status: "active", tasksToday: 42, successRate: 98, avgDuration: "15s", tokensUsed: "34.7K" },
];
