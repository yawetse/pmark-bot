"use client";

// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-010, REQ-UI-011

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bot,
  CircleHelp,
  Database,
  GitBranch,
  MoreHorizontal,
  ServerCog,
  SlidersHorizontal,
  Workflow,
} from "lucide-react";
import { ThemePreferenceControl } from "@/components/dashboard/theme-preference-control";

const PRIMARY_NAV_ITEMS = [
  { href: "/dashboard", label: "Status", icon: Activity },
  { href: "/dashboard/operations", label: "Operations", icon: GitBranch },
  { href: "/dashboard/data", label: "Data", icon: Database },
  { href: "/dashboard/scenario", label: "Scenario", icon: Workflow },
];

const SECONDARY_NAV_ITEMS = [
  { href: "/dashboard/config", label: "Config", icon: SlidersHorizontal },
  { href: "/dashboard/models", label: "Models", icon: Bot },
  { href: "/dashboard/comparison", label: "Performance", icon: BarChart3 },
  { href: "/dashboard/system", label: "System", icon: ServerCog },
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
          <span>codex-poly-bot</span>
        </Link>
        <div className="topbar-actions">
          <nav className="nav" aria-label="Dashboard">
            {PRIMARY_NAV_ITEMS.map((item) => {
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
            <details className="nav-more">
              <summary data-active={SECONDARY_NAV_ITEMS.some((item) => isActivePath(pathname, item.href)) ? "true" : undefined}>
                <MoreHorizontal aria-hidden="true" size={15} strokeWidth={2.3} />
                <span>More</span>
              </summary>
              <div className="nav-more-menu">
                {SECONDARY_NAV_ITEMS.map((item) => {
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
              </div>
            </details>
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
