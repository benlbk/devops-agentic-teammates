"use client";

import { useState } from "react";

interface TaskResultProps {
  result: { status?: string; task_id?: string; message?: string; [key: string]: unknown } | null;
  error: string | null;
  loading: boolean;
}

export function TaskResult({ result, error, loading }: TaskResultProps) {
  if (loading) {
    return (
      <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg animate-pulse">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-blue-700">Submitting task to agent...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-sm font-medium text-red-800">Error</p>
        <p className="text-sm text-red-600 mt-1">{error}</p>
      </div>
    );
  }

  if (result) {
    return (
      <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
        <p className="text-sm font-medium text-green-800">Task Submitted Successfully</p>
        {result.task_id && (
          <p className="text-xs text-green-600 mt-1">Task ID: <code className="bg-green-100 px-1 rounded">{result.task_id}</code></p>
        )}
        {result.message && (
          <p className="text-sm text-green-700 mt-1">{result.message}</p>
        )}
        <details className="mt-2">
          <summary className="text-xs text-green-600 cursor-pointer">View full response</summary>
          <pre className="mt-2 text-xs bg-green-100 p-2 rounded overflow-auto max-h-48">
            {JSON.stringify(result, null, 2)}
          </pre>
        </details>
      </div>
    );
  }

  return null;
}

interface FormFieldProps {
  label: string;
  children: React.ReactNode;
  hint?: string;
}

export function FormField({ label, children, hint }: FormFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}

export function useTaskSubmit() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const execute = async (fn: () => Promise<unknown>) => {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await fn();
      setResult(res as Record<string, unknown>);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return { loading, result, error, execute };
}
