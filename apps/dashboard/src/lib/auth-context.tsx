"use client";

import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export type UserRole = "product-manager" | "developer" | "qa-security" | "devops" | "sre" | "tech-lead";

export interface User {
  name: string;
  email: string;
  role: UserRole;
}

interface AuthContextType {
  user: User | null;
  login: (user: User) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  login: () => {},
  logout: () => {},
  isAuthenticated: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("portal_user");
    if (stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        localStorage.removeItem("portal_user");
      }
    }
  }, []);

  const login = (u: User) => {
    setUser(u);
    localStorage.setItem("portal_user", JSON.stringify(u));
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem("portal_user");
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export const ROLE_CONFIG: Record<UserRole, { label: string; icon: string; description: string }> = {
  "product-manager": { label: "Product Manager", icon: "📋", description: "Feature planning, sprint management, story generation" },
  "developer": { label: "Developer", icon: "💻", description: "Code generation, PR management, dependency checks" },
  "qa-security": { label: "QA / Security", icon: "🔒", description: "Security scans, test generation, vulnerability management" },
  "devops": { label: "DevOps Engineer", icon: "🚀", description: "Deployments, infrastructure, ephemeral environments" },
  "sre": { label: "SRE / Operations", icon: "🔧", description: "Runbooks, incident response, performance optimization" },
  "tech-lead": { label: "Tech Lead", icon: "👑", description: "Approvals, DORA metrics, architecture decisions" },
};
