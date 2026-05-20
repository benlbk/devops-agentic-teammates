"use client";

import { useEffect, useState, useCallback } from "react";
import { getPendingApprovals, submitApproval, PendingApproval } from "@/lib/portal-api";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getPendingApprovals();
      setApprovals(data);
    } catch (err) {
      console.error("Failed to load approvals:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 8000);
    return () => clearInterval(interval);
  }, [load]);

  const handleAction = async (approval: PendingApproval, approved: boolean, comment?: string) => {
    setActionInFlight(approval.task_id);
    try {
      const result = await submitApproval({
        task_id: approval.task_id,
        agent_type: approval.agent_type,
        approved,
        approver: "dashboard-user",
        comment: comment || "",
      });
      setToast({ message: result.message, type: "success" });
      // Remove from list
      setApprovals((prev) => prev.filter((a) => a.task_id !== approval.task_id));
    } catch (err: any) {
      setToast({ message: err?.response?.data?.detail || "Action failed", type: "error" });
    } finally {
      setActionInFlight(null);
      setTimeout(() => setToast(null), 4000);
    }
  };

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading approvals...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Approval Gates</h2>
          <p className="text-sm text-gray-500 mt-1">
            Review and approve merge requests before they go live
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">
            {approvals.length} pending
          </span>
          <button
            onClick={load}
            className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Toast notification */}
      {toast && (
        <div
          className={`px-4 py-3 rounded-lg text-sm font-medium ${
            toast.type === "success"
              ? "bg-green-50 text-green-700 border border-green-200"
              : "bg-red-50 text-red-700 border border-red-200"
          }`}
        >
          {toast.message}
        </div>
      )}

      {approvals.length === 0 ? (
        <div className="bg-white rounded-xl border p-12 text-center">
          <div className="text-4xl mb-3">✅</div>
          <h3 className="text-lg font-medium text-gray-700">All clear</h3>
          <p className="text-sm text-gray-500 mt-1">No pending approvals — everything is up to date</p>
        </div>
      ) : (
        <div className="space-y-4">
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.task_id}
              approval={approval}
              onApprove={() => handleAction(approval, true)}
              onReject={(comment) => handleAction(approval, false, comment)}
              disabled={actionInFlight === approval.task_id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  approval,
  onApprove,
  onReject,
  disabled,
}: {
  approval: PendingApproval;
  onApprove: () => void;
  onReject: (comment: string) => void;
  disabled: boolean;
}) {
  const [showReject, setShowReject] = useState(false);
  const [rejectComment, setRejectComment] = useState("");

  const repo = approval.repository;
  const prNum = approval.pr_number;
  const issueNum = approval.issue_number;
  const reviewSummary =
    approval.output_data?.review_summary || approval.context?.review_summary || "";
  const createdAt = new Date(approval.created_at);
  const age = Math.round((Date.now() - createdAt.getTime()) / 60000);

  return (
    <div className="bg-white rounded-xl border p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 bg-yellow-100 text-yellow-700 text-xs font-medium rounded-full">
              Awaiting Approval
            </span>
            <span className="text-xs text-gray-400">{age}m ago</span>
          </div>

          <h3 className="text-lg font-semibold mt-2">
            {approval.task_type === "merge-approval" ? "Merge PR" : approval.task_type}
            {prNum && (
              <a
                href={`https://github.com/${repo}/pull/${prNum}`}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 text-blue-600 hover:underline"
              >
                #{prNum}
              </a>
            )}
          </h3>

          <div className="flex items-center gap-4 mt-1 text-sm text-gray-500">
            <span>{repo}</span>
            {issueNum && <span>Issue #{issueNum}</span>}
            <span className="font-mono text-xs">{approval.agent_type}</span>
          </div>

          {reviewSummary && (
            <div className="mt-3 bg-gray-50 rounded-lg p-3 text-sm text-gray-700 max-h-32 overflow-y-auto whitespace-pre-wrap">
              {reviewSummary.slice(0, 500)}
              {reviewSummary.length > 500 && "..."}
            </div>
          )}
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        {!showReject ? (
          <>
            <button
              onClick={onApprove}
              disabled={disabled}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {disabled ? "Processing..." : "✓ Approve & Merge"}
            </button>
            <button
              onClick={() => setShowReject(true)}
              disabled={disabled}
              className="px-4 py-2 bg-red-50 hover:bg-red-100 text-red-700 text-sm font-medium rounded-lg border border-red-200 disabled:opacity-50"
            >
              ✕ Reject
            </button>
          </>
        ) : (
          <div className="flex items-center gap-2 flex-1">
            <input
              type="text"
              placeholder="Reason for rejection..."
              value={rejectComment}
              onChange={(e) => setRejectComment(e.target.value)}
              className="flex-1 px-3 py-2 border rounded-lg text-sm"
              autoFocus
            />
            <button
              onClick={() => {
                onReject(rejectComment);
                setShowReject(false);
              }}
              disabled={disabled}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg disabled:opacity-50"
            >
              Confirm Reject
            </button>
            <button
              onClick={() => setShowReject(false)}
              className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
