"use client";

import { useState, useEffect } from "react";
import { submitTask, listRunbooks, executeRunbook, type Runbook } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";

export default function SREPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">🔧 SRE / Operations Console</h1>
        <p className="text-gray-500">Execute runbooks, respond to incidents, analyze performance</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RunbookCard />
        <AlertSimulationCard />
        <PerformanceAnalysisCard />
        <CostAnalysisCard />
      </div>
    </div>
  );
}

function RunbookCard() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [selectedRunbook, setSelectedRunbook] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const { loading, result, error, execute } = useTaskSubmit();

  useEffect(() => {
    listRunbooks()
      .then(setRunbooks)
      .catch(() =>
        setRunbooks([
          { name: "pod_restart", description: "Restart a failing pod", parameters: ["namespace", "pod_name"] },
          { name: "scale_up", description: "Scale deployment replicas", parameters: ["namespace", "deployment", "replicas"] },
          { name: "rollback", description: "Rollback to previous version", parameters: ["namespace", "deployment"] },
          { name: "cache_clear", description: "Clear application cache", parameters: ["namespace", "service"] },
          { name: "hpa_adjust", description: "Adjust HPA thresholds", parameters: ["namespace", "hpa_name", "min", "max"] },
          { name: "dns_check", description: "Diagnose DNS resolution", parameters: ["namespace", "hostname"] },
        ])
      );
  }, []);

  const currentRunbook = runbooks.find((r) => r.name === selectedRunbook);

  const handleRunbookChange = (name: string) => {
    setSelectedRunbook(name);
    const rb = runbooks.find((r) => r.name === name);
    if (rb) {
      const defaults: Record<string, string> = {};
      rb.parameters.forEach((p) => (defaults[p] = ""));
      setParams(defaults);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() => executeRunbook({ runbook: selectedRunbook, parameters: params }));
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Execute Runbook</h3>
      <p className="text-sm text-gray-500 mb-4">
        Run automated remediation scripts. Low/medium severity issues auto-execute if policy allows.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Runbook">
          <select
            value={selectedRunbook}
            onChange={(e) => handleRunbookChange(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select a runbook...</option>
            {runbooks.map((rb) => (
              <option key={rb.name} value={rb.name}>
                {rb.name} — {rb.description}
              </option>
            ))}
          </select>
        </FormField>

        {currentRunbook && (
          <div className="space-y-3 p-3 bg-gray-50 rounded-lg">
            <p className="text-xs font-medium text-gray-600 uppercase">Parameters</p>
            {currentRunbook.parameters.map((param) => (
              <FormField key={param} label={param}>
                <input
                  type="text"
                  value={params[param] || ""}
                  onChange={(e) => setParams((p) => ({ ...p, [param]: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                  placeholder={
                    param === "namespace" ? "target-app" :
                    param === "pod_name" ? "target-backend-xxx" :
                    param === "deployment" ? "target-backend" :
                    param === "replicas" ? "3" :
                    param === "hostname" ? "api.example.com" :
                    ""
                  }
                  required
                />
              </FormField>
            ))}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !selectedRunbook}
          className="w-full py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:opacity-50"
        >
          {loading ? "Executing..." : "Execute Runbook"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function AlertSimulationCard() {
  const [alertName, setAlertName] = useState("HighPodRestartCount");
  const [namespace, setNamespace] = useState("target-app");
  const [pod, setPod] = useState("");
  const [severity, setSeverity] = useState("warning");
  const [summary, setSummary] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "operate-monitor",
        task_type: "incident-response",
        context: {
          alert: {
            status: "firing",
            labels: { alertname: alertName, namespace, pod },
            annotations: { summary, severity },
          },
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Alert Simulation</h3>
      <p className="text-sm text-gray-500 mb-4">
        Simulate a Prometheus alert to test incident response and auto-remediation.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Alert Name">
            <select
              value={alertName}
              onChange={(e) => setAlertName(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="HighPodRestartCount">HighPodRestartCount</option>
              <option value="HighErrorRate">HighErrorRate</option>
              <option value="HighLatency">HighLatency</option>
              <option value="PodCrashLooping">PodCrashLooping</option>
              <option value="DiskPressure">DiskPressure</option>
            </select>
          </FormField>
          <FormField label="Severity">
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          </FormField>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <FormField label="Namespace">
            <input
              type="text"
              value={namespace}
              onChange={(e) => setNamespace(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            />
          </FormField>
          <FormField label="Pod (optional)">
            <input
              type="text"
              value={pod}
              onChange={(e) => setPod(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              placeholder="target-backend-xxx"
            />
          </FormField>
        </div>

        <FormField label="Summary">
          <input
            type="text"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="Pod has restarted 5 times in 10 minutes"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !summary.trim()}
          className="w-full py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Sending..." : "🚨 Simulate Alert"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function PerformanceAnalysisCard() {
  const [service, setService] = useState("target-backend");
  const [symptoms, setSymptoms] = useState("");
  const [metricsWindow, setMetricsWindow] = useState("1h");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "operate-monitor",
        task_type: "performance-analysis",
        context: {
          service,
          namespace: "target-app",
          symptoms,
          metrics_window: metricsWindow,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Performance Analysis</h3>
      <p className="text-sm text-gray-500 mb-4">
        AI analyzes performance metrics and identifies bottlenecks with recommended fixes.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Service">
            <select
              value={service}
              onChange={(e) => setService(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="target-backend">Target Backend</option>
              <option value="target-frontend">Target Frontend</option>
              <option value="agent-orchestrator">Orchestrator</option>
            </select>
          </FormField>
          <FormField label="Time Window">
            <select
              value={metricsWindow}
              onChange={(e) => setMetricsWindow(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="15m">15 minutes</option>
              <option value="1h">1 hour</option>
              <option value="6h">6 hours</option>
              <option value="24h">24 hours</option>
            </select>
          </FormField>
        </div>

        <FormField label="Symptoms" hint="Describe the performance issue you're observing">
          <textarea
            value={symptoms}
            onChange={(e) => setSymptoms(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. P95 latency increased from 200ms to 800ms"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !symptoms.trim()}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Analyze Performance"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function CostAnalysisCard() {
  const [scope, setScope] = useState("all");
  const [period, setPeriod] = useState("last-30-days");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "operate-monitor",
        task_type: "cost-analysis",
        context: { scope, period },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Cost Analysis</h3>
      <p className="text-sm text-gray-500 mb-4">
        Get AI-powered cost breakdown with savings recommendations.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Scope">
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Services</option>
              <option value="compute">Compute (EKS)</option>
              <option value="database">Database (RDS)</option>
              <option value="storage">Storage (S3/EBS)</option>
              <option value="networking">Networking</option>
            </select>
          </FormField>
          <FormField label="Period">
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="last-7-days">Last 7 days</option>
              <option value="last-30-days">Last 30 days</option>
              <option value="last-90-days">Last 90 days</option>
            </select>
          </FormField>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "💰 Analyze Costs"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
