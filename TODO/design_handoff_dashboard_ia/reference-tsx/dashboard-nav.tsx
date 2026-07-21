"use client";

// Redesigned nav: flat, always-visible items, no overflow "More" menu.
// Drop-in replacement for components/dashboard/dashboard-nav.tsx

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, CircleHelp, GitBranch, SlidersHorizontal } from "lucide-react";
import { ThemePreferenceControl } from "@/components/dashboard/theme-preference-control";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: Activity },
  { href: "/dashboard/activity", label: "Activity", icon: GitBranch },
  { href: "/dashboard/performance", label: "Performance", icon: BarChart3 },
  { href: "/dashboard/config", label: "Settings", icon: SlidersHorizontal },
  { href: "/dashboard/help", label: "Help", icon: CircleHelp },
];

export function DashboardNav() {
  const pathname = usePathname();

  return (
    <>
      <a className="skip-link" href="#dashboard-main">
        Skip to main content
      </a>
      <header className="topbar">
        <Link className="brand" href="/dashboard">
          <span>Poly Bot</span>
        </Link>
        <div className="topbar-actions">
          <nav className="nav" aria-label="Dashboard">
            {NAV_ITEMS.map((item) => {
              const active = isActivePath(pathname, item.href);
              const Icon = item.icon;
              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  data-active={active ? "true" : undefined}
                  href={item.href}
                  key={item.href}
                >
                  <Icon aria-hidden="true" size={15} strokeWidth={2.3} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
          <ThemePreferenceControl />
        </div>
      </header>
    </>
  );
}

function isActivePath(pathname: string, href: string): boolean {
  return href === "/dashboard"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}
