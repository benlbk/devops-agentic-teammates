import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "DevOps Agentic Teammates — Dashboard",
  description: "Autonomous SDLC monitoring and management dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-50`}>
        <div className="flex h-screen">
          <Sidebar />
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}

function Sidebar() {
  const navItems = [
    { href: "/", label: "Overview", icon: "📊" },
    { href: "/dora", label: "DORA Metrics", icon: "📈" },
    { href: "/agents", label: "Agent Activity", icon: "🤖" },
    { href: "/environments", label: "Environments", icon: "🌍" },
    { href: "/security", label: "Security", icon: "🔒" },
    { href: "/costs", label: "Costs", icon: "💰" },
    { href: "/settings", label: "Settings", icon: "⚙️" },
  ];

  return (
    <aside className="w-64 bg-gray-900 text-white flex flex-col">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold">Agent Dashboard</h1>
        <p className="text-xs text-gray-400">DevOps Agentic Teammates</p>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => (
          <a
            key={item.href}
            href={item.href}
            className="flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-gray-800 transition-colors"
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </a>
        ))}
      </nav>
    </aside>
  );
}
