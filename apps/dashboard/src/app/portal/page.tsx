"use client";

import { useAuth, ROLE_CONFIG, type UserRole } from "@/lib/auth-context";
import Link from "next/link";

const ROLE_PAGES: Record<UserRole, { href: string; actions: string[] }> = {
  "product-manager": {
    href: "/portal/pm",
    actions: ["Feature Planning", "Sprint Planning", "Story Generation", "ADR Creation"],
  },
  developer: {
    href: "/portal/developer",
    actions: ["Code Generation", "Dependency Check", "PR Merge", "Code Review Status"],
  },
  "qa-security": {
    href: "/portal/qa",
    actions: ["Security Scan", "Test Generation", "Container Scan", "IaC Scan"],
  },
  devops: {
    href: "/portal/devops",
    actions: ["Deploy Status", "Terraform Plan", "Ephemeral Environments", "Rollback"],
  },
  sre: {
    href: "/portal/sre",
    actions: ["Execute Runbook", "Performance Analysis", "Cost Analysis", "Alert Simulation"],
  },
  "tech-lead": {
    href: "/portal/techlead",
    actions: ["Pending Approvals", "DORA Metrics", "Policy Review", "ADR Generation"],
  },
};

export default function PortalHome() {
  const { user } = useAuth();
  if (!user) return null;

  const config = ROLE_CONFIG[user.role];
  const page = ROLE_PAGES[user.role];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Welcome, {user.name}</h1>
        <p className="text-gray-500 mt-1">{config.description}</p>
      </div>

      {/* Quick actions for current role */}
      <div className="bg-white rounded-xl border p-6">
        <h2 className="text-lg font-semibold mb-4">Your Operations</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {page.actions.map((action) => (
            <Link
              key={action}
              href={page.href}
              className="p-4 bg-blue-50 rounded-lg text-center hover:bg-blue-100 transition-colors"
            >
              <span className="block text-sm font-medium text-blue-900">{action}</span>
            </Link>
          ))}
        </div>
        <div className="mt-4">
          <Link
            href={page.href}
            className="inline-flex items-center text-blue-600 hover:text-blue-800 font-medium text-sm"
          >
            Go to {config.label} Console →
          </Link>
        </div>
      </div>

      {/* All roles overview */}
      <div>
        <h2 className="text-lg font-semibold mb-4">All Role Consoles</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(Object.entries(ROLE_PAGES) as [UserRole, typeof ROLE_PAGES[UserRole]][]).map(([role, info]) => {
            const rc = ROLE_CONFIG[role];
            const isCurrent = role === user.role;
            return (
              <Link
                key={role}
                href={info.href}
                className={`p-4 rounded-xl border transition-all hover:shadow-md ${
                  isCurrent ? "border-blue-500 bg-blue-50" : "border-gray-200 bg-white"
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{rc.icon}</span>
                  <span className="font-semibold text-gray-900">{rc.label}</span>
                  {isCurrent && (
                    <span className="ml-auto text-xs bg-blue-200 text-blue-800 px-2 py-0.5 rounded">You</span>
                  )}
                </div>
                <p className="text-xs text-gray-500">{rc.description}</p>
              </Link>
            );
          })}
        </div>
      </div>

      {/* Platform health */}
      <div className="bg-white rounded-xl border p-6">
        <h2 className="text-lg font-semibold mb-3">Platform Quick Links</h2>
        <div className="flex flex-wrap gap-3">
          <Link href="/" className="text-sm text-blue-600 hover:underline">📊 Monitoring Dashboard</Link>
          <Link href="/dora" className="text-sm text-blue-600 hover:underline">📈 DORA Metrics</Link>
          <Link href="/agents" className="text-sm text-blue-600 hover:underline">🤖 Agent Activity</Link>
          <Link href="/security" className="text-sm text-blue-600 hover:underline">🔒 Security</Link>
          <Link href="/environments" className="text-sm text-blue-600 hover:underline">🌍 Environments</Link>
          <Link href="/costs" className="text-sm text-blue-600 hover:underline">💰 Costs</Link>
        </div>
      </div>
    </div>
  );
}
