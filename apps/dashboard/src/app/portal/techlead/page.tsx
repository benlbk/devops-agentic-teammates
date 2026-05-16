"use client";

import { useState, useEffect } from "react";
import { submitTask, submitApproval, getPendingApprovals, getDORAMetrics, type Approval } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";
import { useAuth } from "@/lib/auth-context";

export default function TechLeadPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">👑 Tech Lead Console</h1>
        <p className="text-gray-500">Approve deployments, review metrics, manage architecture decisions</p>
      </div>

      <div className="grid grid-cols-1 gap-6">
        <ApprovalQueueCard />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DORAMetricsCard />
        <ADRGenerationCard />
      </div>
    </div>
  );
}

function ApprovalQueueCard() {
  const { user } = useAuth();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loadingApprovals, setLoadingApprovals] = useState(true);
  const [actionResult, setActionResult] = useState<{ taskId: string; result: string } | null>(null);

  useEffect(() => {
    loadApprovals();
  }, []);

  const loadApprovals = async () => {
    setLoadingApprovals(true);
    try {
      const data = await getPendingApprovals();
      setApprovals(data);
    } catch {
      setApprovals([]);
    } finally {
      setLoadingApprovals(false);
    }
  };

  const handleDecision = async (taskId: string, decision: "approved" | "rejected", comment: string) => {
    try {
      await submitApproval({
        task_id: taskId,
        decision,
        approver: user?.name || "tech-lead",
        comment,
      });
      setActionResult({ taskId, result: `${decision} successfully` });
      loadApprovals();
    } catch (e) {
      setActionResult({ taskId, result: `Error: ${e instanceof Error ? e.message : "Unknown"}` });
    }
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Pending Approvals</h3>
        <button
          onClick={loadApprovals}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          ↻ Refresh
        </button>
      </div>

      {loadingApprovals ? (
        <div className="text-sm text-gray-500 animate-pulse">Loading approvals...</div>
      ) : approvals.length === 0 ? (
        <div className="text-center py-8 text-gray-400">
          <p className="text-4xl mb-2">✓</p>
          <p className="text-sm">No pending approvals</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((approval) => (
            <ApprovalItem
              key={approval.task_id}
              approval={approval}
              onDecision={handleDecision}
            />
          ))}
        </div>
      )}

      {actionResult && (
        <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700">
          Task {actionResult.taskId.slice(0, 8)}... → {actionResult.result}
        </div>
      )}
    </div>
  );
}

function ApprovalItem({
  approval,
  onDecision,
}: {
  approval: Approval;
  onDecision: (taskId: string, decision: "approved" | "rejected", comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Task: {approval.task_id.slice(0, 12)}...</p>
          <p className="text-xs text-gray-500">Status: {approval.status} | Created: {approval.created_at || "—"}</p>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-600"
        >
          {expanded ? "Collapse" : "Review"}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm"
            placeholder="Add a comment (optional)..."
          />
          <div className="flex gap-2">
            <button
              onClick={() => onDecision(approval.task_id, "approved", comment)}
              className="flex-1 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700"
            >
              ✓ Approve
            </button>
            <button
              onClick={() => onDecision(approval.task_id, "rejected", comment)}
              className="flex-1 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700"
            >
              ✗ Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DORAMetricsCard() {
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDORAMetrics()
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">DORA Metrics</h3>
      <p className="text-sm text-gray-500 mb-4">
        Track team delivery performance with the four key DORA metrics.
      </p>

      {loading ? (
        <div className="animate-pulse space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 bg-gray-100 rounded" />
          ))}
        </div>
      ) : metrics ? (
        <div className="space-y-3">
          <MetricRow label="Deployment Frequency" value={metrics} keyName="deployment_frequency" />
          <MetricRow label="Lead Time for Changes" value={metrics} keyName="lead_time_for_changes" />
          <MetricRow label="Change Failure Rate" value={metrics} keyName="change_failure_rate" />
          <MetricRow label="Mean Time to Recovery" value={metrics} keyName="mean_time_to_recovery" />
        </div>
      ) : (
        <p className="text-sm text-gray-400">Unable to load metrics</p>
      )}

      <div className="mt-4">
        <a href="/dora" className="text-sm text-blue-600 hover:underline">View detailed DORA dashboard →</a>
      </div>
    </div>
  );
}

function MetricRow({ label, value, keyName }: { label: string; value: Record<string, unknown>; keyName: string }) {
  const metric = value[keyName] as { value?: number; unit?: string } | undefined;
  return (
    <div className="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <span className="text-sm font-bold text-blue-700">
        {metric ? `${metric.value} ${metric.unit || ""}` : "—"}
      </span>
    </div>
  );
}

function ADRGenerationCard() {
  const [decision, setDecision] = useState("");
  const [drivers, setDrivers] = useState("");
  const [options, setOptions] = useState("");
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "plan-collaborate",
        task_type: "adr-generation",
        context: {
          decision,
          drivers: drivers.split("\n").filter((d) => d.trim()),
          options_considered: options.split("\n").filter((o) => o.trim()),
          repository,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Generate ADR</h3>
      <p className="text-sm text-gray-500 mb-4">
        Create an Architecture Decision Record documenting a technical decision.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Decision" hint="What architectural decision are you making?">
          <input
            type="text"
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Migrate from REST to GraphQL for the BFF layer"
            required
          />
        </FormField>

        <FormField label="Drivers (one per line)" hint="Why is this decision needed?">
          <textarea
            value={drivers}
            onChange={(e) => setDrivers(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder={"Frontend needs to fetch from 5+ services per page\nOver-fetching causing performance issues"}
          />
        </FormField>

        <FormField label="Options Considered (one per line)">
          <textarea
            value={options}
            onChange={(e) => setOptions(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder={"GraphQL\nBFF with REST aggregation\ntRPC"}
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !decision.trim()}
          className="w-full py-2 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Generating..." : "Generate ADR"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
