"use client";

import { FormEvent, useEffect, useState } from "react";

import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-004, REQ-OBS-004, REQ-OBS-005

export type DashboardTheme = "system" | "light" | "dark";

export type UserPreferenceSettings = {
  theme: DashboardTheme;
  timeZone: string;
  awsMonthlyInfraCostUsd: string;
};

export type UserPreferencesView = {
  environment: string;
  username: string;
  settings: UserPreferenceSettings;
  updatedAt?: string | null;
};

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; message: string }
  | { status: "error"; message: string };

const TIME_ZONES = [
  "system",
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Asia/Tokyo",
  "Australia/Sydney",
];

export function PreferencesPanel({
  preferences,
  onSaved,
}: {
  preferences: UserPreferenceSettings;
  onSaved: (settings: UserPreferenceSettings) => void;
}) {
  const [draft, setDraft] = useState<UserPreferenceSettings>(preferences);
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  useEffect(() => {
    setDraft(preferences);
    applyDashboardTheme(preferences.theme);
  }, [preferences]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaveState({ status: "saving" });
    const result = await dashboardApi<UserPreferencesView>("preferences", {
      method: "PUT",
      body: JSON.stringify({ settings: draft }),
    });
    if (!result.ok) {
      setSaveState({ status: "error", message: result.message });
      return;
    }
    onSaved(result.data.settings);
    applyDashboardTheme(result.data.settings.theme);
    setSaveState({ status: "saved", message: "Preferences saved." });
  }

  return (
    <section className="operator-panel" aria-labelledby="preferences-title">
      <div>
        <p className="section-label">Preferences</p>
        <h2 id="preferences-title">User settings</h2>
      </div>
      <form className="form-stack" onSubmit={onSubmit}>
        <label>
          Theme
          <select
            value={draft.theme}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                theme: event.target.value as DashboardTheme,
              }))
            }
          >
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
        <label>
          Time zone
          <select
            value={draft.timeZone}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                timeZone: event.target.value,
              }))
            }
          >
            {TIME_ZONES.map((timeZone) => (
              <option key={timeZone} value={timeZone}>
                {timeZone === "system" ? "System time zone" : timeZone}
              </option>
            ))}
          </select>
        </label>
        <label>
          AWS monthly infra cost
          <input
            inputMode="decimal"
            min="0"
            step="0.01"
            type="number"
            value={draft.awsMonthlyInfraCostUsd}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                awsMonthlyInfraCostUsd: event.target.value,
              }))
            }
          />
        </label>
        <button className="button primary" disabled={saveState.status === "saving"} type="submit">
          {saveState.status === "saving" ? "Saving" : "Save preferences"}
        </button>
      </form>
      {saveState.status === "saved" || saveState.status === "error" ? (
        <p className="status-message">{saveState.message}</p>
      ) : null}
    </section>
  );
}

export function applyDashboardTheme(theme: DashboardTheme) {
  if (typeof document === "undefined") {
    return;
  }
  if (theme === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.dataset.theme = theme;
  }
  try {
    window.localStorage.setItem("codex-poly-bot-theme", theme);
  } catch {
    return;
  }
}
