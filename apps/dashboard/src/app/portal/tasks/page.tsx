"use client";

import { useEffect, useState, useCallback } from "react";
import { getTaskDetail, getTasksByStatus, TaskDetail } from "@/lib/portal-api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  "in-progress": "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  "awaiting-approval": "bg-purple-100 text-purple-800",
  cancelled: "bg-gray-100 text-gray-600",
};

const AGENT_LABELS: Record<string, string> = {
  "plan-collaborate": "Plan & Collaborate",
  "code-build": "Code & Build",
  "test-secure": "Test & Secure",
  "release-deploy": "Release & Deploy",
  "operate-monitor": "Operate & Monitor",
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskDetail[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [searchId, setSearchId] = useState("");

  const loadTasks = useCallback(async () => {
    try {
      const statuses = ["pending", "in-progress", "completed", "failed"];
      const allTasks: TaskDetail[] = [];
      for (const status of statuses) {
        const result = await getTasksByStatus(status);
        allTasks.push(...result);
      }
      allTasks.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setTasks(allTasks);
    } catch (err) {
      console.error("Failed to load tasks:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 10000); // Auto-refresh every 10s
    return () => clearInterval(interval);
  }, [loadTasks]);

  const handleSearch = async () => {
    if (!searchId.trim()) return;
    try {
      // Try common agent types
      const agents = ["plan-collaborate", "code-build", "test-secure", "release-deploy", "operate-monitor"];
      for (const agent of agents) {
        try {
          const task = await getTaskDetail(agent, searchId.trim());
          if (task) {
            setSelectedTask(task);
            return;
          }
        } catch { /* try next */ }
      }
    } catch (err) {
      console.error("Task not found:", err);
    }
  };

  const filteredTasks = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight">Task Monitor</h2>
        <button
          onClick={loadTasks}
          className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Search by Task ID */}
      <div className="bg-white rounded-xl border p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            placeholder="Search by Task ID (e.g. 09b5ad5e-2f26-415a-a356-...)"
            className="flex-1 px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Search
          </button>
        </div>
      </div>

      {/* Task Detail Modal */}
      {selectedTask && (
        <TaskDetailCard task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}

      {/* Filter tabs */}
      <div className="flex gap-2">
        {["all", "pending", "in-progress", "completed", "failed"].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
              filter === s ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"
            }`}
          >
            {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Task List */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading tasks...</div>
      ) : filteredTasks.length === 0 ? (
        <div className="text-center py-12 text-gray-500">No tasks found</div>
      ) : (
        <div className="space-y-3">
          {filteredTasks.map((task) => (
            <div
              key={task.task_id}
              onClick={() => setSelectedTask(task)}
              className="bg-white rounded-xl border p-4 cursor-pointer hover:border-blue-300 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[task.status] || "bg-gray-100"}`}>
                    {task.status}
                  </span>
                  <span className="text-sm font-medium">
                    {AGENT_LABELS[task.agent_type] || task.agent_type}
                  </span>
                  <span className="text-sm text-gray-500">{task.task_type}</span>
                </div>
                <span className="text-xs text-gray-400">
                  {new Date(task.created_at).toLocaleString()}
                </span>
              </div>
              <p className="mt-2 text-xs text-gray-500 font-mono truncate">
                ID: {task.task_id}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TaskDetailCard({ task, onClose }: { task: TaskDetail; onClose: () => void }) {
  const [refreshing, setRefreshing] = useState(false);
  const [current, setCurrent] = useState(task);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const updated = await getTaskDetail(current.agent_type, current.task_id);
      setCurrent(updated);
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  // Auto-refresh if pending/in-progress
  useEffect(() => {
    if (current.status === "pending" || current.status === "in-progress") {
      const interval = setInterval(refresh, 5000);
      return () => clearInterval(interval);
    }
  }, [current.status]);

  return (
    <div className="bg-white rounded-xl border p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Task Details</h3>
        <div className="flex gap-2">
          <button
            onClick={refresh}
            disabled={refreshing}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
          >
            {refreshing ? "..." : "↻"}
          </button>
          <button
            onClick={onClose}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
          >
            ✕
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-gray-500">Task ID</span>
          <p className="font-mono text-xs mt-0.5 break-all">{current.task_id}</p>
        </div>
        <div>
          <span className="text-gray-500">Status</span>
          <p className="mt-0.5">
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[current.status] || "bg-gray-100"}`}>
              {current.status}
            </span>
          </p>
        </div>
        <div>
          <span className="text-gray-500">Agent</span>
          <p className="mt-0.5 font-medium">{AGENT_LABELS[current.agent_type] || current.agent_type}</p>
        </div>
        <div>
          <span className="text-gray-500">Task Type</span>
          <p className="mt-0.5">{current.task_type}</p>
        </div>
        <div>
          <span className="text-gray-500">Created</span>
          <p className="mt-0.5">{new Date(current.created_at).toLocaleString()}</p>
        </div>
        <div>
          <span className="text-gray-500">Started</span>
          <p className="mt-0.5">{current.started_at ? new Date(current.started_at).toLocaleString() : "—"}</p>
        </div>
        <div>
          <span className="text-gray-500">Completed</span>
          <p className="mt-0.5">{current.completed_at ? new Date(current.completed_at).toLocaleString() : "—"}</p>
        </div>
        <div>
          <span className="text-gray-500">Tokens Used</span>
          <p className="mt-0.5">{current.tokens_used.toLocaleString()}</p>
        </div>
      </div>

      {current.error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm font-medium text-red-800">Error</p>
          <p className="text-xs text-red-700 mt-1 font-mono">{current.error}</p>
        </div>
      )}

      {current.context && Object.keys(current.context).length > 0 && (
        <div>
          <p className="text-sm text-gray-500 mb-1">Context</p>
          <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto max-h-40">
            {JSON.stringify(current.context, null, 2)}
          </pre>
        </div>
      )}

      {current.output_data && Object.keys(current.output_data).length > 0 && (
        <div>
          <p className="text-sm text-gray-500 mb-1">Output</p>
          <pre className="bg-green-50 rounded-lg p-3 text-xs overflow-auto max-h-40">
            {JSON.stringify(current.output_data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
