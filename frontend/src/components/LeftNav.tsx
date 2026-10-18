import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import type { UserRole } from "../api/types";
import { ROLE_DESCRIPTIONS } from "../auth/roleRoutes";

interface NavItem {
  label: string;
  badge?: string;
  to: string;
  icon: React.FC<{ className?: string }>;
  matchPrefix?: boolean;
}

// Icons
const OverviewIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
  </svg>
);

const TriageIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

const ControlIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const ReposIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
    <path d="M6 6h10" />
    <path d="M6 10h10" />
  </svg>
);

const MemoryIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const UsersIcon: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

function getNavItemsForRole(role?: UserRole): NavItem[] {
  switch (role) {
    case "viewer":
      return [
        {
          label: "Overview",
          to: "/overview",
          icon: OverviewIcon,
        },
        {
          label: "Repositories",
          badge: "(read-only)",
          to: "/repos",
          icon: ReposIcon,
          matchPrefix: true,
        },
        {
          label: "Memory",
          to: "/memory",
          icon: MemoryIcon,
          matchPrefix: true,
        },
      ];

    case "analyst":
      return [
        {
          label: "Triage",
          to: "/triage",
          icon: TriageIcon,
        },
        {
          label: "Repositories",
          badge: "(with Add)",
          to: "/repos",
          icon: ReposIcon,
          matchPrefix: true,
        },
        {
          label: "Memory",
          to: "/memory",
          icon: MemoryIcon,
          matchPrefix: true,
        },
      ];

    case "admin":
      return [
        {
          label: "Control Center",
          to: "/control",
          icon: ControlIcon,
        },
        {
          label: "Triage",
          to: "/triage",
          icon: TriageIcon,
        },
        {
          label: "Repositories",
          to: "/repos",
          icon: ReposIcon,
          matchPrefix: true,
        },
        {
          label: "Memory",
          to: "/memory",
          icon: MemoryIcon,
          matchPrefix: true,
        },
        {
          label: "Users",
          to: "/admin/users",
          icon: UsersIcon,
          matchPrefix: true,
        },
      ];

    default:
      return [];
  }
}

export const LeftNav: React.FC = () => {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) {
    return null;
  }

  const items = getNavItemsForRole(user.role);

  return (
    <aside
      aria-label="Sidebar Navigation"
      className="w-64 flex-shrink-0 bg-bg-surface/90 border-r border-border flex flex-col justify-between select-none"
    >
      <div className="p-3 space-y-1">
        <div className="px-3 py-2 text-[11px] font-mono uppercase tracking-wider text-gray-500 font-semibold">
          Menu
        </div>
        <nav className="space-y-1">
          {items.map((item) => {
            const Icon = item.icon;
            const isMatch =
              location.pathname === item.to ||
              (item.matchPrefix &&
                item.to !== "/" &&
                location.pathname.startsWith(item.to));

            return (
              <Link
                key={item.to + (item.badge || "")}
                to={item.to}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors group ${
                  isMatch
                    ? "bg-accent/15 text-white font-medium border border-accent/30 shadow-sm"
                    : "text-gray-400 hover:text-gray-200 hover:bg-bg-card/70"
                }`}
                title={item.label}
              >
                <Icon
                  className={`w-4 h-4 transition-colors flex-shrink-0 ${
                    isMatch
                      ? "text-accent"
                      : "text-gray-400 group-hover:text-gray-300"
                  }`}
                />
                <span className="truncate">{item.label}</span>
                {item.badge && (
                  <span
                    className={`ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded border flex-shrink-0 ${
                      user.role === "viewer"
                        ? "bg-slate-500/10 text-slate-300 border-slate-500/30"
                        : "bg-accent/10 text-accent border-accent/25"
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Role Summary Card at Sidebar Footer */}
      <div className="p-3 border-t border-border/80 bg-bg-card/30">
        <div className="rounded-lg bg-bg-card/60 border border-border p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase font-mono text-gray-400 font-semibold">
              Current Role
            </span>
            <span
              className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                user.role === "admin"
                  ? "bg-purple-500/15 text-purple-300 border border-purple-500/30"
                  : user.role === "analyst"
                  ? "bg-blue-500/15 text-blue-300 border border-blue-500/30"
                  : "bg-slate-500/15 text-slate-300 border border-slate-500/30"
              }`}
            >
              {user.role}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 leading-snug">
            {ROLE_DESCRIPTIONS[user.role]}
          </p>
        </div>
      </div>
    </aside>
  );
};

export default LeftNav;
