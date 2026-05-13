export default function SecurityPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Security</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <StatCard label="Critical" value={0} color="bg-red-500" />
        <StatCard label="High" value={2} color="bg-orange-500" />
        <StatCard label="Medium" value={8} color="bg-yellow-500" />
        <StatCard label="Low" value={15} color="bg-blue-500" />
      </div>

      <div className="rounded-lg border bg-white p-6">
        <h3 className="text-lg font-semibold mb-4">Scan History</h3>
        <div className="space-y-3">
          <ScanRow type="SAST" tool="CodeQL + Semgrep" lastRun="30m ago" findings={3} status="pass" />
          <ScanRow type="SCA" tool="Dependabot + Snyk" lastRun="1h ago" findings={5} status="warn" />
          <ScanRow type="Container" tool="Trivy" lastRun="2h ago" findings={2} status="pass" />
          <ScanRow type="IaC" tool="Checkov + tfsec" lastRun="3h ago" findings={0} status="pass" />
          <ScanRow type="Secrets" tool="Gitleaks" lastRun="30m ago" findings={0} status="pass" />
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center gap-2">
        <span className={`h-3 w-3 rounded-full ${color}`} />
        <span className="text-sm text-gray-500">{label}</span>
      </div>
      <p className="mt-1 text-3xl font-bold">{value}</p>
    </div>
  );
}

function ScanRow({ type, tool, lastRun, findings, status }: {
  type: string; tool: string; lastRun: string; findings: number; status: string;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b last:border-0">
      <div>
        <p className="font-medium text-sm">{type}</p>
        <p className="text-xs text-gray-500">{tool}</p>
      </div>
      <div className="flex items-center gap-6 text-sm">
        <span className="text-gray-500">{lastRun}</span>
        <span>{findings} findings</span>
        <span className={`px-2 py-0.5 rounded text-xs ${
          status === "pass" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
        }`}>{status}</span>
      </div>
    </div>
  );
}
