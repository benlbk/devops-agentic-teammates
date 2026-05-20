"use client";

import { useEffect, useState, useCallback } from "react";
import { getPipelineStatus, PipelineIssue, PipelineStage } from "@/lib/portal-api";

const STAGES = ["planning", "code_generation", "review", "fix", "merge"] as const;

const STAGE_LABELS: Record<string, string> = {
  planning: "Planning",
  code_generation: "Code Gen",
  review: "Review",
  fix: "Auto-Fix",
  merge: "Merged",
};

const STAGE_ICONS: Record<string, string> = {
  planning: "📋",
  code_generation: "⚡",
  review: "🔍",
  fix: "🔧",
  merge: "✅",
};

const STATUS_STYLES: Record<string, { bg: string; dot: string; text: string }> = {
  completed: { bg: "bg-green-50", dot: "bg-green-500", text: "text-green-700" },
  "in-progress": { bg: "bg-blue-50", dot: "bg-blue-500 animate-pulse", text: "text-blue-700" },
  pending: { bg: "bg-yellow-50", dot: "bg-yellow-500", text: "text-yellow-700" },
  failed: { bg: "bg-red-50", dot: "bg-red-500", text: "text-red-700" },
};

export default function PipelinePage() {
  const [owner, setOwner] = useState("benlbk");
  const [repo, setRepo] = useState("online-shopping-app");
  const [issues, setIssues] = useState<PipelineIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const loadPipeline = useCallback(async () => {
    try {
      const data = await getPipelineStatus(owner, repo);
      setIssues(data.issues);
      setLastUpdated(new Date());
    } catch (err) {
      console.error("Failed to load pipeline:", err);
    } finally {
      setLoading(false);
    }
  }, [owner, repo]);

  useEffect(() => {
    loadPipeline();
    const interval = setInterval(loadPipeline, 8000);
    return () => clearInterval(interval);
  }, [loadPipeline]);

  const hasActive = issues.some((i) =>
    Object.values(i.stages).some((s) => s.status === "in-progress" || s.status === "pending")
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Pipeline Status</h2>
          <p className="text-sm text-gray-500 mt-1">
            Real-time view of issue → code → review → merge flow
          </p>
        </div>
        <div className="flex items-center gap-3">
          {hasActive && (
            <span className="flex items-center gap-1.5 text-xs text-blue-600">
              <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              Live
            </span>
          )}
          {lastUpdated && (
            <span className="text-xs text-gray-400">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={loadPipeline}
            className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Repo selector */}
      <div className="bg-white rounded-xl border p-4">
        <div className="flex gap-2 items-center">
          <label className="text-sm text-gray-500">Repository:</label>
          <input
            type="text"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            className="px-3 py-1.5 border rounded-lg text-sm w-32"
            placeholder="owner"
          />
          <span className="text-gray-400">/</span>
          <input
            type="text"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="px-3 py-1.5 border rounded-lg text-sm w-48"
            placeholder="repo"
          />
          <button
            onClick={() => { setLoading(true); loadPipeline(); }}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Load
          </button>
        </div>
      </div>

      {/* Stage header */}
      <div className="hidden md:grid md:grid-cols-6 gap-2 px-4">
        <div className="text-xs font-medium text-gray-500 uppercase">Issue</div>
        {STAGES.map((stage) => (
          <div key={stage} className="text-xs font-medium text-gray-500 uppercase text-center">
            {STAGE_ICONS[stage]} {STAGE_LABELS[stage]}
          </div>
        ))}
      </div>

      {/* Pipeline rows */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading pipeline...</div>
      ) : issues.length === 0 ? (
        <div className="text-center py-12 text-gray-500">No issues found for this repository</div>
      ) : (
        <div className="space-y-3">
          {issues.map((issue) => (
            <PipelineRow key={issue.issue_number} issue={issue} />
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-6 text-xs text-gray-500 pt-4 border-t">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-green-500" /> Completed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" /> In Progress
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-yellow-500" /> Pending
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-red-500" /> Failed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-gray-300" /> Not Started
        </span>
      </div>
    </div>
  );
}

function PipelineRow({ issue }: { issue: PipelineIssue }) {
  const issueState = issue.state || (
    Object.values(issue.stages).every((s) => s.status === "completed") ? "closed" : "open"
  );

  return (
    <div className="bg-white rounded-xl border p-4 hover:border-blue-200 transition-colors">
      <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-center">
        {/* Issue info */}
        <div className="flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${
            issueState === "closed" ? "bg-purple-100 text-purple-700" : "bg-green-100 text-green-700"
          }`}>
            #{issue.issue_number}
          </span>
          <span className="text-sm font-medium truncate" title={issue.title}>
            {issue.title}
          </span>
        </div>

        {/* Stage cells */}
        {STAGES.map((stage) => (
          <StageCell key={stage} stage={issue.stages[stage]} label={STAGE_LABELS[stage]} />
        ))}
      </div>

      {/* Labels */}
      {issue.labels && issue.labels.length > 0 && (
        <div className="mt-2 flex gap-1 flex-wrap md:pl-0">
          {issue.labels.map((label) => (
            <span key={label} className="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-600">
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function StageCell({ stage, label }: { stage?: PipelineStage; label: string }) {
  if (!stage) {
    return (
      <div className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg bg-gray-50">
        <span className="h-2 w-2 rounded-full bg-gray-300" />
        <span className="text-xs text-gray-400">{label}</span>
      </div>
    );
  }

  const style = STATUS_STYLES[stage.status] || STATUS_STYLES.pending;
  const prUrl = stage.output?.pr_url as string | undefined;

  return (
    <div className={`flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg ${style.bg}`}>
      <span className={`h-2 w-2 rounded-full ${style.dot}`} />
      <span className={`text-xs font-medium ${style.text}`}>
        {prUrl ? (
          <a href={prUrl} target="_blank" rel="noopener noreferrer" className="underline">
            {label}
          </a>
        ) : (
          label
        )}
      </span>
    </div>
  );
}
