"use client";

import { FormEvent, useState } from "react";

import { dashboardApi } from "@/lib/api";
import {
  ALLOWED_CONFIG_PATHS,
  isAllowedConfigPath,
} from "@/lib/config-paths";
import type { AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-ALP-014, REQ-NOT-006

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
  applies_on_next_loop?: boolean;
};

type SaveState =
  | { status: "idle" }
  | { status: "saved"; version: string }
  | { status: "conflict"; currentVersion: string }
  | { status: "error"; message: string };

export function ConfigControls() {
  const [path, setPath] = useState<AllowedConfigPath>(ALLOWED_CONFIG_PATHS[0]);
  const [value, setValue] = useState("true");
  const [expectedVersion, setExpectedVersion] = useState("");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isAllowedConfigPath(path)) {
      setSaveState({ status: "error", message: "Unsupported config path" });
      return;
    }

    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "PUT",
      body: JSON.stringify({
        environment: process.env.NEXT_PUBLIC_APP_ENV ?? "local",
        expected_version: expectedVersion || null,
        patches: [{ op: "replace", path, value: parseValue(value) }],
      }),
    });

    if (!result.ok) {
      const currentVersion = parseCurrentVersion(result.message);
      if (result.status === 409 && currentVersion) {
        setSaveState({ status: "conflict", currentVersion });
        return;
      }
      setSaveState({ status: "error", message: result.message });
      return;
    }

    setSaveState({ status: "saved", version: result.data.new_version ?? "unknown" });
  }

  return (
    <section className="panel">
      <h2>Config</h2>
      <form className="form-stack" onSubmit={onSubmit}>
        <label>
          Path
          <select
            value={path}
            onChange={(event) => {
              if (isAllowedConfigPath(event.target.value)) {
                setPath(event.target.value);
              }
            }}
          >
            {ALLOWED_CONFIG_PATHS.map((allowedPath) => (
              <option key={allowedPath} value={allowedPath}>
                {allowedPath}
              </option>
            ))}
          </select>
        </label>
        <label>
          Value
          <input value={value} onChange={(event) => setValue(event.target.value)} />
        </label>
        <label>
          Expected version
          <input
            value={expectedVersion}
            onChange={(event) => setExpectedVersion(event.target.value)}
            placeholder="Current version"
          />
        </label>
        <button className="button primary" type="submit">
          Save
        </button>
      </form>
      {saveState.status === "saved" ? (
        <p className="status-message">Saved version {saveState.version}. Applies on next loop.</p>
      ) : null}
      {saveState.status === "conflict" ? (
        <p className="status-message">
          Current server version is {saveState.currentVersion}. Reload before resubmitting.
        </p>
      ) : null}
      {saveState.status === "error" ? <p className="status-message">{saveState.message}</p> : null}
    </section>
  );
}

function parseValue(value: string): string | boolean | number {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  const numericValue = Number(value);
  return Number.isFinite(numericValue) && value.trim() !== "" ? numericValue : value;
}

function parseCurrentVersion(message: string): string | null {
  try {
    const payload = JSON.parse(message) as { current_version?: string };
    return payload.current_version ?? null;
  } catch {
    return null;
  }
}
