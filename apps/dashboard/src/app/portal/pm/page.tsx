"use client";

import { useState } from "react";
import { submitTask } from "@/lib/portal-api";
import { TaskResult, FormField, useTaskSubmit } from "../components";

export default function PMPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">📋 Product Manager Console</h1>
        <p className="text-gray-500">Plan features, generate stories, manage sprints</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FeaturePlanningCard />
        <SprintPlanningCard />
      </div>
    </div>
  );
}

function FeaturePlanningCard() {
  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState("");
  const [repository, setRepository] = useState("");
  const [targetStack, setTargetStack] = useState("Next.js frontend + .NET backend + PostgreSQL");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const repo = repository.trim()
      ? (repository.trim().includes("/") ? repository.trim() : `benlbk/${repository.trim()}`)
      : "benlbk/devops-agentic-teammates";
    execute(() =>
      submitTask({
        agent_type: "plan-collaborate",
        task_type: "feature-planning",
        context: {
          featureDescription: description,
          description,
          repository: repo,
          requirements: requirements.split("\n").filter((r) => r.trim()),
          target_stack: targetStack,
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Feature Planning</h3>
      <p className="text-sm text-gray-500 mb-4">
        Describe a feature and the AI agent will generate user stories, GitHub Issues, and spec documents.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Target Repository" hint="Where to create issues (leave empty for default)">
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. my-ecommerce-app or benlbk/my-ecommerce-app"
          />
        </FormField>

        <FormField label="Feature Description" hint="Describe the feature you want to build">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Build a user authentication system with social login..."
            required
          />
        </FormField>

        <FormField label="Requirements (one per line)">
          <textarea
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder={"Support Google OAuth\nEmail/password registration\nJWT session management"}
          />
        </FormField>

        <FormField label="Target Stack">
          <input
            type="text"
            value={targetStack}
            onChange={(e) => setTargetStack(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          />
        </FormField>

        <button
          type="submit"
          disabled={loading || !description.trim()}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Submitting..." : "Generate Feature Plan"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}

function SprintPlanningCard() {
  const [sprintGoal, setSprintGoal] = useState("");
  const [capacityDays, setCapacityDays] = useState("10");
  const [teamSize, setTeamSize] = useState("3");
  const [projectRepo, setProjectRepo] = useState("");
  const { loading, result, error, execute } = useTaskSubmit();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    execute(() =>
      submitTask({
        agent_type: "plan-collaborate",
        task_type: "sprint-planning",
        context: {
          sprint_goal: sprintGoal,
          capacity_days: parseInt(capacityDays),
          team_size: parseInt(teamSize),
          ...(projectRepo.trim() && { project_repo: projectRepo.trim() }),
        },
      })
    );
  };

  return (
    <div className="bg-white rounded-xl border p-6">
      <h3 className="text-lg font-semibold mb-4">Sprint Planning</h3>
      <p className="text-sm text-gray-500 mb-4">
        Define a sprint goal and the agent will suggest scope based on capacity and velocity.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Sprint Goal">
          <input
            type="text"
            value={sprintGoal}
            onChange={(e) => setSprintGoal(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Complete user authentication MVP"
            required
          />
        </FormField>

        <FormField label="Project Repository (new repo for generated code)">
          <input
            type="text"
            value={projectRepo}
            onChange={(e) => setProjectRepo(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. my-ecommerce-app (leave empty to use source repo)"
          />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField label="Capacity (days)">
            <input
              type="number"
              value={capacityDays}
              onChange={(e) => setCapacityDays(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              min="1"
              max="30"
            />
          </FormField>
          <FormField label="Team Size">
            <input
              type="number"
              value={teamSize}
              onChange={(e) => setTeamSize(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              min="1"
              max="20"
            />
          </FormField>
        </div>

        <button
          type="submit"
          disabled={loading || !sprintGoal.trim()}
          className="w-full py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Submitting..." : "Plan Sprint"}
        </button>
      </form>

      <TaskResult result={result} error={error} loading={loading} />
    </div>
  );
}
