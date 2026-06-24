"use client";

import { FormEvent, useState } from "react";

import { dashboardApi } from "@/lib/api";
import {
  ALLOWED_CONFIG_PATHS,
  CONFIG_PATH_DETAILS,
  isAllowedConfigPath,
} from "@/lib/config-paths";
import type { AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-ALP-014, REQ-NOT-006

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
  applies_on_next_loop?: boolean;
};

export type ConfigSnapshot = {
  environment: string;
  version: string;
  settings: Record<string, unknown>;
  degraded?: boolean;
};

type SaveState =
  | { status: "idle" }
  | { status: "saved"; version: string }
  | { status: "conflict"; currentVersion: string }
  | { status: "error"; message: string };

type ConfigControlsProps = {
  initialSnapshot?: ConfigSnapshot;
  loadError?: string;
};

export function ConfigControls({ initialSnapshot, loadError }: ConfigControlsProps) {
  const [settings, setSettings] = useState(initialSnapshot?.settings);
  const [path, setPath] = useState<AllowedConfigPath>(ALLOWED_CONFIG_PATHS[0]);
  const [value, setValue] = useState(() =>
    formatValueForInput(valueAtPath(initialSnapshot?.settings, ALLOWED_CONFIG_PATHS[0])),
  );
  const [expectedVersion, setExpectedVersion] = useState(() =>
    expectedVersionFromSnapshot(initialSnapshot),
  );
  const [currentVersion, setCurrentVersion] = useState(initialSnapshot?.version ?? "");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const selectedDetail = CONFIG_PATH_DETAILS[path];
  const currentValue = valueAtPath(settings, path);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isAllowedConfigPath(path)) {
      setSaveState({ status: "error", message: "Unsupported config path" });
      return;
    }

    const parsedValue = parseValue(value);
    if (!parsedValue.ok) {
      setSaveState({ status: "error", message: parsedValue.message });
      return;
    }

    const nextVersion = nextConfigVersion(currentVersion);
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "PUT",
      body: JSON.stringify({
        environment: initialSnapshot?.environment ?? process.env.NEXT_PUBLIC_APP_ENV ?? "local",
        version: nextVersion,
        expected_version: expectedVersion || null,
        patches: [{ op: "replace", path, value: parsedValue.value }],
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

    const savedVersion = result.data.new_version ?? nextVersion;
    setSettings((currentSettings) => valueAtUpdatedPath(currentSettings, path, parsedValue.value));
    setCurrentVersion(savedVersion);
    setExpectedVersion(savedVersion);
    setSaveState({ status: "saved", version: savedVersion });
  }

  function onPathChange(nextPath: string) {
    if (!isAllowedConfigPath(nextPath)) {
      return;
    }
    setPath(nextPath);
    setValue(formatValueForInput(valueAtPath(settings, nextPath)));
    setSaveState({ status: "idle" });
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-label">Controls</p>
          <h2>Config</h2>
        </div>
        <span className="status ok">applies next loop</span>
      </div>
      {initialSnapshot ? (
        <p>
          Current version: {currentVersion || initialSnapshot.version}. Environment:{" "}
          {initialSnapshot.environment}.
        </p>
      ) : null}
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <form className="form-stack" onSubmit={onSubmit}>
        <label>
          Path
          <select
            value={path}
            onChange={(event) => onPathChange(event.target.value)}
          >
            {ALLOWED_CONFIG_PATHS.map((allowedPath) => (
              <option key={allowedPath} value={allowedPath}>
                {CONFIG_PATH_DETAILS[allowedPath].label}
              </option>
            ))}
          </select>
        </label>
        <div className="setting-help">
          <strong>{selectedDetail.label}</strong>
          <p>{selectedDetail.description}</p>
          <dl>
            <div>
              <dt>Path</dt>
              <dd>{path}</dd>
            </div>
            <div>
              <dt>Current value</dt>
              <dd>{formatValueForInput(currentValue) || "not set"}</dd>
            </div>
            <div>
              <dt>Expected value</dt>
              <dd>{selectedDetail.valueHint}</dd>
            </div>
            <div>
              <dt>Effect</dt>
              <dd>{selectedDetail.effect}</dd>
            </div>
          </dl>
        </div>
        <label>
          Value
          <textarea
            rows={pathRequiresJson(path) ? 6 : 3}
            placeholder={selectedDetail.valueHint}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
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

function parseValue(
  value: string,
): { ok: true; value: string | boolean | number | string[] | Record<string, unknown> } | { ok: false; message: string } {
  const trimmed = value.trim();
  if (trimmed === "true") {
    return { ok: true, value: true };
  }
  if (trimmed === "false") {
    return { ok: true, value: false };
  }
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (Array.isArray(parsed) || isPlainObject(parsed)) {
        return { ok: true, value: parsed };
      }
      return { ok: false, message: "JSON values must be an array or object" };
    } catch {
      return { ok: false, message: "Value is not valid JSON" };
    }
  }
  const numericValue = Number(trimmed);
  if (Number.isFinite(numericValue) && trimmed !== "") {
    return { ok: true, value: numericValue };
  }
  return { ok: true, value };
}

function parseCurrentVersion(message: string): string | null {
  try {
    const payload = JSON.parse(message) as { current_version?: string };
    return payload.current_version ?? null;
  } catch {
    return null;
  }
}

function expectedVersionFromSnapshot(snapshot?: ConfigSnapshot): string {
  if (!snapshot || snapshot.version === "bootstrap") {
    return "";
  }
  return snapshot.version;
}

function nextConfigVersion(currentVersion: string): string {
  const match = /^v(\d+)$/.exec(currentVersion);
  if (match) {
    return `v${Number(match[1]) + 1}`;
  }
  return `ui-${Date.now()}`;
}

function valueAtPath(settings: Record<string, unknown> | undefined, path: string): unknown {
  if (!settings) {
    return true;
  }
  return path.split(".").reduce<unknown>((current, segment) => {
    if (isPlainObject(current)) {
      return current[segment];
    }
    return undefined;
  }, settings);
}

function valueAtUpdatedPath(
  settings: Record<string, unknown> | undefined,
  path: string,
  value: unknown,
): Record<string, unknown> | undefined {
  if (!settings) {
    return settings;
  }
  const next = { ...settings };
  const segments = path.split(".");
  let current: Record<string, unknown> = next;
  for (const segment of segments.slice(0, -1)) {
    const child = current[segment];
    const nextChild = isPlainObject(child) ? { ...child } : {};
    current[segment] = nextChild;
    current = nextChild;
  }
  current[segments[segments.length - 1]] = value;
  return next;
}

function formatValueForInput(value: unknown): string {
  if (value === undefined) {
    return "";
  }
  if (Array.isArray(value) || isPlainObject(value)) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function pathRequiresJson(path: AllowedConfigPath): boolean {
  return path === "alpaca.symbol_universe" || path === "notifications.recipients";
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
