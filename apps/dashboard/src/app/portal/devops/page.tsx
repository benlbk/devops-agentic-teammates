"use client";

import { useState } from "react";
import { submitTask } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";

export default function DevOpsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">🚀 DevOps Engineer Console</h1>
        <p className="text-gray-500">Manage deployments, infrastructure, and environments</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TerraformPlanCard />
        <EphemeralEnvCard />
        <DeployStatusCard />
        <RollbackCard />
      </div>
    </div>
  );
}

function TerraformPlanCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [module, setModule] = useState("terraform/modules/rds-postgresql");
  const [changeDescription, setChangeDescription] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "release-deploy",
        task_type: "terraform-plan-review",
        context: {
          repository,
          module,
          change_description: changeDescription,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Terraform Plan Review</h3>
      <p className="text-sm text-gray-500 mb-4">
        Run terraform plan and get AI analysis of infrastructure changes with risk and cost assessment.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Repository">
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          />
        </FormField>

        <FormField label="Terraform Module">
          <select
            value={module}
            onChange={(e) => setModule(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          >
            <option value="terraform/modules/vpc">VPC</option>
            <option value="terraform/modules/eks-cluster">EKS Cluster</option>
            <option value="terraform/modules/rds-postgresql">RDS PostgreSQL</option>
            <option value="terraform/modules/dynamodb">DynamoDB</option>
            <option value="terraform/modules/eventbridge">EventBridge</option>
            <option value="terraform/modules/ecr">ECR</option>
            <option value="terraform/modules/api-gateway">API Gateway</option>
          </select>
        </FormField>

        <FormField label="Change Description" hint="What infrastructure change are you making?">
          <textarea
            value={changeDescription}
            onChange={(e) => setChangeDescription(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Increase RDS instance size from db.t3.medium to db.t3.large"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !changeDescription.trim()}
          className="w-full py-2 bg-orange-600 text-white rounded-lg font-medium hover:bg-orange-700 disabled:opacity-50"
        >
          {loading ? "Planning..." : "Run Terraform Plan"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function EphemeralEnvCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [prNumber, setPrNumber] = useState("");
  const [services, setServices] = useState({ frontend: true, backend: true });
  const [ttlHours, setTtlHours] = useState("24");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const selectedServices = Object.entries(services)
      .filter(([, v]) => v)
      .map(([k]) => k);

    execute(() =>
      submitTask({
        agent_type: "release-deploy",
        task_type: "ephemeral-environment",
        context: {
          pr_number: parseInt(prNumber),
          repository,
          services: selectedServices,
          ttl_hours: parseInt(ttlHours),
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Ephemeral Environment</h3>
      <p className="text-sm text-gray-500 mb-4">
        Create a per-PR preview environment with selected services deployed in an isolated namespace.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Repository">
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField label="PR Number">
            <input
              type="number"
              value={prNumber}
              onChange={(e) => setPrNumber(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. 15"
              min="1"
              required
            />
          </FormField>
          <FormField label="TTL (hours)">
            <input
              type="number"
              value={ttlHours}
              onChange={(e) => setTtlHours(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              min="1"
              max="168"
            />
          </FormField>
        </div>

        <FormField label="Services to Deploy">
          <div className="flex gap-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={services.frontend}
                onChange={() => setServices((p) => ({ ...p, frontend: !p.frontend }))}
                className="rounded text-blue-600"
              />
              <span className="text-sm">Frontend</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={services.backend}
                onChange={() => setServices((p) => ({ ...p, backend: !p.backend }))}
                className="rounded text-blue-600"
              />
              <span className="text-sm">Backend</span>
            </label>
          </div>
        </FormField>

        <button
          type="submit"
          disabled={loading || !prNumber}
          className="w-full py-2 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700 disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create Environment"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function DeployStatusCard() {
  const [service, setService] = useState("target-backend");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "release-deploy",
        task_type: "deployment-status",
        context: { service, namespace: "target-app" },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Deployment Status</h3>
      <p className="text-sm text-gray-500 mb-4">
        Check the current deployment status, rollout progress, and sync state.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Service">
          <select
            value={service}
            onChange={(e) => setService(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          >
            <option value="target-backend">Target Backend</option>
            <option value="target-frontend">Target Frontend</option>
            <option value="agent-orchestrator">Agent Orchestrator</option>
          </select>
        </FormField>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Checking..." : "Check Status"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function RollbackCard() {
  const [service, setService] = useState("target-backend");
  const [reason, setReason] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "release-deploy",
        task_type: "rollback",
        context: {
          service,
          namespace: "target-app",
          reason,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Rollback Deployment</h3>
      <p className="text-sm text-gray-500 mb-4">
        Rollback a service to the previous stable version. Requires approval for production.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Service">
          <select
            value={service}
            onChange={(e) => setService(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          >
            <option value="target-backend">Target Backend</option>
            <option value="target-frontend">Target Frontend</option>
          </select>
        </FormField>

        <FormField label="Reason" hint="Why are you rolling back?">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. 5xx error rate spike after latest deploy"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !reason.trim()}
          className="w-full py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Rolling back..." : "⚠️ Rollback"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
