export default function CostsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Cost Analysis</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">Monthly Spend (MTD)</p>
          <p className="mt-1 text-2xl font-bold">$4,832</p>
          <p className="text-xs text-green-600">-8% vs last month</p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">Forecast</p>
          <p className="mt-1 text-2xl font-bold">$7,200</p>
          <p className="text-xs text-gray-500">Based on current usage</p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">Potential Savings</p>
          <p className="mt-1 text-2xl font-bold text-green-600">$1,450</p>
          <p className="text-xs text-gray-500">6 recommendations</p>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-6">
        <h3 className="text-lg font-semibold mb-4">Cost Breakdown by Service</h3>
        <div className="space-y-3">
          <CostRow service="EKS (Compute)" cost={2100} pct={43} />
          <CostRow service="RDS PostgreSQL" cost={850} pct={18} />
          <CostRow service="CloudFront CDN" cost={420} pct={9} />
          <CostRow service="OpenSearch" cost={380} pct={8} />
          <CostRow service="EventBridge" cost={120} pct={2} />
          <CostRow service="Other (DynamoDB, ECR, etc.)" cost={962} pct={20} />
        </div>
      </div>
    </div>
  );
}

function CostRow({ service, cost, pct }: { service: string; cost: number; pct: number }) {
  return (
    <div className="flex items-center gap-4">
      <span className="w-48 text-sm font-medium">{service}</span>
      <div className="flex-1 bg-gray-100 rounded-full h-3">
        <div className="bg-blue-500 h-3 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-mono w-20 text-right">${cost.toLocaleString()}</span>
    </div>
  );
}
