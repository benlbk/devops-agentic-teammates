export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold tracking-tight">
        Target Application
      </h1>
      <p className="mt-4 text-lg text-gray-600">
        Modern web application managed by DevOps Agentic Teammates
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <FeatureCard title="Next.js 14" description="App Router with Server Components" />
        <FeatureCard title="ASP.NET Core 8" description="High-performance backend API" />
        <FeatureCard title="PostgreSQL" description="Reliable relational database" />
      </div>
    </main>
  );
}

function FeatureCard({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-lg border border-gray-200 p-6 hover:border-primary-500 transition-colors">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-gray-500">{description}</p>
    </div>
  );
}
