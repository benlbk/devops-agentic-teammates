export default function EnvironmentsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Environments</h2>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <EnvCard name="Production" status="healthy" version="v1.8.3" lastDeploy="2h ago" pods="3/3" />
        <EnvCard name="Staging" status="healthy" version="v1.8.4-rc1" lastDeploy="45m ago" pods="2/2" />
        <EnvCard name="Development" status="healthy" version="v1.9.0-dev" lastDeploy="15m ago" pods="2/2" />
      </div>

      <h3 className="text-xl font-semibold mt-8">Ephemeral Environments</h3>
      <div className="rounded-lg border bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-3 font-medium">PR</th>
              <th className="px-4 py-3 font-medium">Branch</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">URL</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            <EphemeralRow pr="#142" branch="feat/user-dashboard" status="running" url="pr-142.preview.example.com" created="1h ago" />
            <EphemeralRow pr="#139" branch="fix/auth-flow" status="running" url="pr-139.preview.example.com" created="3h ago" />
            <EphemeralRow pr="#136" branch="feat/notifications" status="destroying" url="-" created="1d ago" />
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EnvCard({ name, status, version, lastDeploy, pods }: {
  name: string; status: string; version: string; lastDeploy: string; pods: string;
}) {
  return (
    <div className="rounded-lg border bg-white p-6">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold">{name}</h4>
        <span className={`h-3 w-3 rounded-full ${status === "healthy" ? "bg-green-500" : "bg-red-500"}`} />
      </div>
      <div className="space-y-1 text-sm text-gray-600">
        <p>Version: <span className="font-mono">{version}</span></p>
        <p>Last Deploy: {lastDeploy}</p>
        <p>Pods: {pods}</p>
      </div>
    </div>
  );
}

function EphemeralRow({ pr, branch, status, url, created }: {
  pr: string; branch: string; status: string; url: string; created: string;
}) {
  return (
    <tr>
      <td className="px-4 py-3 font-medium">{pr}</td>
      <td className="px-4 py-3 font-mono text-xs">{branch}</td>
      <td className="px-4 py-3">
        <span className={`px-2 py-0.5 rounded text-xs ${
          status === "running" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
        }`}>{status}</span>
      </td>
      <td className="px-4 py-3 text-blue-600 text-xs">{url}</td>
      <td className="px-4 py-3 text-gray-500">{created}</td>
    </tr>
  );
}
