"use client";

import { useEffect, useState } from "react";

import {
  applyDashboardTheme,
  type DashboardTheme,
  type UserPreferencesView,
  type UserPreferenceSettings,
} from "@/components/dashboard/preferences-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-004, REQ-OBS-004, REQ-OBS-005

const DEFAULT_SETTINGS: UserPreferenceSettings = {
  theme: "system",
  timeZone: "system",
  awsMonthlyInfraCostUsd: "30.00",
};

const THEMES: Array<{ label: string; value: DashboardTheme }> = [
  { label: "System", value: "system" },
  { label: "Light", value: "light" },
  { label: "Dark", value: "dark" },
];

export function ThemePreferenceControl() {
  const [settings, setSettings] = useState<UserPreferenceSettings>(DEFAULT_SETTINGS);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "error">("idle");

  useEffect(() => {
    const localTheme = localThemePreference();
    if (localTheme) {
      setSettings((current) => ({ ...current, theme: localTheme }));
      applyDashboardTheme(localTheme);
    }
    let cancelled = false;
    async function loadPreferences() {
      const result = await dashboardApi<UserPreferencesView>("preferences");
      if (!cancelled && result.ok) {
        setSettings(result.data.settings);
        applyDashboardTheme(result.data.settings.theme);
      }
    }
    void loadPreferences();
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveTheme(theme: DashboardTheme) {
    const nextSettings = { ...settings, theme };
    setSettings(nextSettings);
    setSaveState("saving");
    applyDashboardTheme(theme);
    const result = await dashboardApi<UserPreferencesView>("preferences", {
      method: "PUT",
      body: JSON.stringify({ settings: nextSettings }),
    });
    if (!result.ok) {
      setSaveState("error");
      return;
    }
    setSettings(result.data.settings);
    applyDashboardTheme(result.data.settings.theme);
    setSaveState("idle");
  }

  return (
    <div className="theme-control" aria-label="Theme preference">
      <span>Theme</span>
      <div className="theme-options" role="group" aria-label="Theme preference">
        {THEMES.map((theme) => (
          <button
            aria-pressed={settings.theme === theme.value}
            className={`theme-option ${settings.theme === theme.value ? "active" : ""}`}
            disabled={saveState === "saving"}
            key={theme.value}
            type="button"
            onClick={() => saveTheme(theme.value)}
          >
            {theme.label}
          </button>
        ))}
      </div>
      {saveState === "error" ? <span className="theme-save-error">Save failed</span> : null}
    </div>
  );
}

function localThemePreference(): DashboardTheme | null {
  try {
    const theme = window.localStorage.getItem("codex-poly-bot-theme");
    return theme === "system" || theme === "light" || theme === "dark" ? theme : null;
  } catch {
    return null;
  }
}
