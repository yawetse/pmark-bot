"use client";

// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-010, REQ-UI-011

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemePreferenceControl } from "@/components/dashboard/theme-preference-control";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Status" },
  { href: "/dashboard/config", label: "Config" },
  { href: "/dashboard/models/claude", label: "Claude" },
  { href: "/dashboard/models/openai", label: "OpenAI" },
  { href: "/dashboard/comparison", label: "Comparison" },
  { href: "/dashboard/operations", label: "Operations" },
  { href: "/dashboard/system", label: "System" },
  { href: "/dashboard/help", label: "Help" },
];

export function DashboardNav() {
  const pathname = usePathname();

  return (
    <header className="topbar">
      <Link className="brand" href="/dashboard">
        codex-poly-bot
      </Link>
      <div className="topbar-actions">
        <nav className="nav" aria-label="Dashboard">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === "/dashboard"
                ? pathname === item.href
                : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                data-active={active ? "true" : undefined}
                href={item.href}
                key={item.href}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <ThemePreferenceControl />
      </div>
    </header>
  );
}
