"use client";

import { useState } from "react";
import { submitTask, checkDependencies, requestMerge } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";

export default function DeveloperPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">💻 Developer Console</h1>
        <p className="text-gray-500">Generate code, check dependencies, manage PRs</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CodeGenerationCard />
        <DependencyCheckCard />
        <MergeCoordinationCard />
        <CodeReviewCard />
      </div>
    </div>
  );
}

function CodeGenerationCard() {
  const [specification, setSpecification] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "code-build",
        task_type: "code-generation",
        context: {
          repository,
          specification,
          target_path: targetPath || undefined,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">AI Code Generation</h3>
      <p className="text-sm text-gray-500 mb-4">
        Describe what you want to build. The agent generates code, creates a branch, and opens a PR.
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

        <FormField label="Specification" hint="Describe the code to generate">
          <textarea
            value={specification}
            onChange={(e) => setSpecification(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Create a Next.js page at /auth/login with email/password form and OAuth buttons"
            required
          />
        </FormField>

        <FormField label="Target Path (optional)" hint="File path for the generated code">
          <input
            type="text"
            value={targetPath}
            onChange={(e) => setTargetPath(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. apps/frontend/src/app/auth/login/page.tsx"
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !specification.trim()}
          className="w-full py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:opacity-50"
        >
          {loading ? "Generating..." : "Generate Code"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function DependencyCheckCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [packageManager, setPackageManager] = useState("npm");
  const [path, setPath] = useState("apps/frontend/package.json");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      checkDependencies({ repository, package_manager: packageManager, path })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Dependency Check</h3>
      <p className="text-sm text-gray-500 mb-4">
        Scan dependencies for outdated packages and known vulnerabilities.
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
          <FormField label="Package Manager">
            <select
              value={packageManager}
              onChange={(e) => setPackageManager(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="npm">npm</option>
              <option value="nuget">NuGet</option>
              <option value="poetry">Poetry</option>
            </select>
          </FormField>
          <FormField label="Manifest Path">
            <input
              type="text"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            />
          </FormField>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:opacity-50"
        >
          {loading ? "Scanning..." : "Check Dependencies"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function MergeCoordinationCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [prNumber, setPrNumber] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      requestMerge({ repository, pr_number: parseInt(prNumber) })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">PR Merge Coordination</h3>
      <p className="text-sm text-gray-500 mb-4">
        Request a coordinated merge with all checks (reviews, tests, security, policy).
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

        <FormField label="PR Number">
          <input
            type="number"
            value={prNumber}
            onChange={(e) => setPrNumber(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. 42"
            min="1"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !prNumber}
          className="w-full py-2 bg-purple-600 text-white rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50"
        >
          {loading ? "Processing..." : "Merge PR"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function CodeReviewCard() {
  const [repository, setRepository] = useState("benlbk/devops-agentic-teammates");
  const [prNumber, setPrNumber] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "code-build",
        task_type: "code-review",
        context: {
          repository,
          pr_number: parseInt(prNumber),
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Trigger AI Code Review</h3>
      <p className="text-sm text-gray-500 mb-4">
        Manually trigger an AI code review on any PR (auto-runs on PR open/update).
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

        <FormField label="PR Number">
          <input
            type="number"
            value={prNumber}
            onChange={(e) => setPrNumber(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. 10"
            min="1"
            required
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !prNumber}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Submitting..." : "Request Review"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
