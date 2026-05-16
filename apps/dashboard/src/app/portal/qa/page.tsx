"use client";

import { useState } from "react";
import { submitTask } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";

export default function QAPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">🔒 QA / Security Console</h1>
        <p className="text-gray-500">Run security scans, generate tests, check vulnerabilities</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SecurityScanCard />
        <TestGenerationCard />
      </div>
    </div>
  );
}

function SecurityScanCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [branch, setBranch] = useState("main");
  const [scanTypes, setScanTypes] = useState({
    sast: true,
    sca: true,
    container: true,
    iac: true,
    secrets: true,
  });
  const { loading, result, error, execute } = useTaskSubmit();

  const toggleScan = (key: keyof typeof scanTypes) => {
    setScanTypes((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const selectedScans = Object.entries(scanTypes)
      .filter(([, v]) => v)
      .map(([k]) => k);

    execute(() =>
      submitTask({
        agent_type: "test-secure",
        task_type: "security-scan",
        context: {
          repository,
          scan_types: selectedScans,
          branch,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Security Scan</h3>
      <p className="text-sm text-gray-500 mb-4">
        Run comprehensive security scans: SAST, SCA, container, IaC, and secrets detection.
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

        <FormField label="Branch">
          <input
            type="text"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          />
        </FormField>

        <FormField label="Scan Types">
          <div className="grid grid-cols-2 gap-2">
            {(Object.entries(scanTypes) as [keyof typeof scanTypes, boolean][]).map(([key, enabled]) => (
              <label key={key} className="flex items-center gap-2 p-2 border rounded-lg cursor-pointer hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => toggleScan(key)}
                  className="rounded text-blue-600"
                />
                <span className="text-sm capitalize">{key}</span>
                <span className="text-xs text-gray-400">
                  {key === "sast" && "(Semgrep)"}
                  {key === "sca" && "(Trivy)"}
                  {key === "container" && "(Trivy)"}
                  {key === "iac" && "(Checkov)"}
                  {key === "secrets" && "(Gitleaks)"}
                </span>
              </label>
            ))}
          </div>
        </FormField>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Scanning..." : "Run Security Scan"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function TestGenerationCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [targetFiles, setTargetFiles] = useState("");
  const [testTypes, setTestTypes] = useState({ unit: true, integration: false });
  const [framework, setFramework] = useState("xUnit");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const types = Object.entries(testTypes)
      .filter(([, v]) => v)
      .map(([k]) => k);

    execute(() =>
      submitTask({
        agent_type: "test-secure",
        task_type: "test-generation",
        context: {
          repository,
          target_files: targetFiles.split("\n").filter((f) => f.trim()),
          test_types: types,
          framework,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Test Generation</h3>
      <p className="text-sm text-gray-500 mb-4">
        AI generates unit and integration tests for the specified source files.
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

        <FormField label="Target Files (one per line)" hint="Source files to generate tests for">
          <textarea
            value={targetFiles}
            onChange={(e) => setTargetFiles(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="apps/backend/Controllers/AuthController.cs"
            required
          />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField label="Test Types">
            <div className="space-y-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={testTypes.unit}
                  onChange={() => setTestTypes((p) => ({ ...p, unit: !p.unit }))}
                  className="rounded text-blue-600"
                />
                <span className="text-sm">Unit Tests</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={testTypes.integration}
                  onChange={() => setTestTypes((p) => ({ ...p, integration: !p.integration }))}
                  className="rounded text-blue-600"
                />
                <span className="text-sm">Integration Tests</span>
              </label>
            </div>
          </FormField>
          <FormField label="Framework">
            <select
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="xUnit">xUnit (.NET)</option>
              <option value="jest">Jest (TypeScript)</option>
              <option value="pytest">pytest (Python)</option>
              <option value="playwright">Playwright (E2E)</option>
            </select>
          </FormField>
        </div>

        <button
          type="submit"
          disabled={loading || !targetFiles.trim()}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Generating..." : "Generate Tests"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
