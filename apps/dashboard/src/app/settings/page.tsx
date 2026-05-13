export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Settings</h2>

      <div className="rounded-lg border bg-white p-6 space-y-6">
        <Section title="Agent Configuration">
          <SettingRow label="LLM Provider" value="AWS Bedrock" />
          <SettingRow label="LLM Model" value="anthropic.claude-sonnet-4-20250514" />
          <SettingRow label="Auto-approve low-risk deploys" value="Enabled" />
          <SettingRow label="Max concurrent agent tasks" value="10" />
        </Section>

        <Section title="GitHub Integration">
          <SettingRow label="Account" value="benlbk" />
          <SettingRow label="Auth Method" value="Personal Access Token (PAT)" />
          <SettingRow label="Webhook Status" value="Active ✓" />
        </Section>

        <Section title="Notification Channels">
          <SettingRow label="Slack" value="Connected — #devops-alerts" />
          <SettingRow label="PagerDuty" value="Connected" />
          <SettingRow label="Email" value="devops-team@example.com" />
        </Section>

        <Section title="Policy Rules">
          <SettingRow label="Active Policies" value="8 rules" />
          <SettingRow label="Last Updated" value="2 days ago" />
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-2 border-b last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}
