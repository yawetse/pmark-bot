"use client";

import { FormEvent, useState } from "react";

import { Disclosure } from "@/components/dashboard/dashboard-primitives";
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

type ConfigPatchDraft = {
  path: AllowedConfigPath;
  value: ConfigValue;
};

type ConfigValue = string | boolean | number | string[] | Record<string, unknown>;
type PresetMetadata = {
  presetName: string;
  status: string;
  source: string;
  symbolCount: number;
  snapshotSymbolCount: number;
  customSymbolCount: number;
  refreshedAt: string | null;
  ageHours: number | null;
  message: string | null;
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

const CONFIG_GROUPS: Array<{
  title: string;
  body: string;
  paths: AllowedConfigPath[];
}> = [
  {
    title: "Venue and live mode",
    body: "Choose where the bot can operate and whether live mode can be considered.",
    paths: ["default_selected_venue", "live_enabled", "venues.polymarket_us.enabled"],
  },
  {
    title: "Risk controls",
    body: "Limit size, slippage, exposure, and loss before any order can pass gates.",
    paths: [
      "risk.alpaca.max_position_usd",
      "risk.alpaca.market_order_slippage_threshold",
      "trading_loop_interval_seconds",
    ],
  },
  {
    title: "Model budgets",
    body: "Keep provider usage and scoring costs visible before the next run.",
    paths: ["llm.openai.budget_usd", "llm.claude.budget_usd"],
  },
  {
    title: "Notifications",
    body: "Control who receives alerts and how quickly repeated alerts can fire.",
    paths: ["notifications.recipients", "notifications.cooldown_seconds"],
  },
];

export function ConfigControls({ initialSnapshot, loadError }: ConfigControlsProps) {
  const [settings, setSettings] = useState(initialSnapshot?.settings);
  const [path, setPath] = useState<AllowedConfigPath>(ALLOWED_CONFIG_PATHS[0]);
  const [value, setValue] = useState(() =>
    formatValueForInput(valueAtPath(initialSnapshot?.settings, ALLOWED_CONFIG_PATHS[0])),
  );
  const [presetDraft, setPresetDraft] = useState(() =>
    formatPresetList(valueAtPath(initialSnapshot?.settings, "alpaca.symbol_presets")),
  );
  const [customSymbolDraft, setCustomSymbolDraft] = useState(() =>
    formatSymbolList(valueAtPath(initialSnapshot?.settings, "alpaca.custom_symbols")),
  );
  const [customPresetDraft, setCustomPresetDraft] = useState(() =>
    formatValueForInput(valueAtPath(initialSnapshot?.settings, "alpaca.custom_presets") ?? {}),
  );
  const [expectedVersion, setExpectedVersion] = useState(() =>
    expectedVersionFromSnapshot(initialSnapshot),
  );
  const [currentVersion, setCurrentVersion] = useState(initialSnapshot?.version ?? "");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const selectedDetail = CONFIG_PATH_DETAILS[path];
  const currentValue = valueAtPath(settings, path);
  const resolvedSymbols = symbolsFromValue(valueAtPath(settings, "alpaca.symbol_universe"));
  const presetMetadata = presetMetadataFromValue(valueAtPath(settings, "alpaca.preset_metadata"));
  const refreshEnabled = valueAtPath(settings, "alpaca.preset_refresh.enabled");
  const refreshCadence = valueAtPath(settings, "alpaca.preset_refresh.cadence_hours");
  const staleAfter = valueAtPath(settings, "alpaca.preset_refresh.stale_after_hours");

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

    await saveConfigPatch(path, parsedValue.value);
  }

  async function onStockUniverseSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedPresets = parsePresetList(presetDraft);
    if (!parsedPresets.ok) {
      setSaveState({ status: "error", message: parsedPresets.message });
      return;
    }
    const parsedCustomSymbols = parseSymbols(customSymbolDraft, { allowEmpty: true });
    if (!parsedCustomSymbols.ok) {
      setSaveState({ status: "error", message: parsedCustomSymbols.message });
      return;
    }
    const parsedCustomPresets = parseCustomPresets(customPresetDraft);
    if (!parsedCustomPresets.ok) {
      setSaveState({ status: "error", message: parsedCustomPresets.message });
      return;
    }
    await saveConfigPatches([
      { path: "alpaca.symbol_presets", value: parsedPresets.value },
      { path: "alpaca.custom_symbols", value: parsedCustomSymbols.value },
      { path: "alpaca.custom_presets", value: parsedCustomPresets.value },
    ]);
  }

  async function saveConfigPatch(patchPath: AllowedConfigPath, nextValue: ConfigValue) {
    await saveConfigPatches([{ path: patchPath, value: nextValue }]);
  }

  async function saveConfigPatches(patches: ConfigPatchDraft[]) {
    const nextVersion = nextConfigVersion(currentVersion);
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "PUT",
      body: JSON.stringify({
        environment: initialSnapshot?.environment ?? process.env.NEXT_PUBLIC_APP_ENV ?? "local",
        version: nextVersion,
        expected_version: expectedVersion || null,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
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
    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (refreshed.ok) {
      setSettings(refreshed.data.settings);
      setCurrentVersion(refreshed.data.version);
      setExpectedVersion(expectedVersionFromSnapshot(refreshed.data));
      syncStockUniverseDrafts(refreshed.data.settings);
      setValue(formatValueForInput(valueAtPath(refreshed.data.settings, path)));
      setSaveState({ status: "saved", version: refreshed.data.version });
      return;
    }
    setSettings((currentSettings) =>
      patches.reduce(
        (nextSettings, patch) => valueAtUpdatedPath(nextSettings, patch.path, patch.value),
        currentSettings,
      ),
    );
    setCurrentVersion(savedVersion);
    setExpectedVersion(savedVersion);
    setSaveState({ status: "saved", version: savedVersion });
  }

  function syncStockUniverseDrafts(nextSettings: Record<string, unknown>) {
    setPresetDraft(formatPresetList(valueAtPath(nextSettings, "alpaca.symbol_presets")));
    setCustomSymbolDraft(formatSymbolList(valueAtPath(nextSettings, "alpaca.custom_symbols")));
    setCustomPresetDraft(formatValueForInput(valueAtPath(nextSettings, "alpaca.custom_presets") ?? {}));
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
      <div className="config-group-grid" aria-label="Common configuration groups">
        {CONFIG_GROUPS.map((group) => (
          <article className="config-group-card" key={group.title}>
            <strong>{group.title}</strong>
            <p>{group.body}</p>
            <div className="config-path-actions">
              {group.paths.map((groupPath) => (
                <button
                  className={`config-path-button ${path === groupPath ? "active" : ""}`}
                  key={groupPath}
                  type="button"
                  onClick={() => onPathChange(groupPath)}
                >
                  {CONFIG_PATH_DETAILS[groupPath].label}
                </button>
              ))}
            </div>
          </article>
        ))}
      </div>
      <form className="symbol-editor" onSubmit={onStockUniverseSubmit}>
        <div>
          <h3>Alpaca stock universe</h3>
          <p>
            Manual and scheduled Alpaca pulls combine built-in presets, custom preset groups, and
            individual symbols.
          </p>
        </div>
        <label>
          Active presets
          <textarea
            rows={3}
            value={presetDraft}
            onChange={(event) => setPresetDraft(event.target.value)}
            placeholder="sp500, nasdaq100"
          />
        </label>
        <label>
          Additional symbols
          <textarea
            rows={3}
            value={customSymbolDraft}
            onChange={(event) => setCustomSymbolDraft(event.target.value)}
            placeholder="CRCL, FIG"
          />
        </label>
        <label>
          Custom presets
          <textarea
            rows={5}
            value={customPresetDraft}
            onChange={(event) => setCustomPresetDraft(event.target.value)}
            placeholder='{"new_ipos":["CRCL","FIG"]}'
          />
        </label>
        <p className="panel-note">
          Resolved symbols: {resolvedSymbols.length}. First symbols:{" "}
          {resolvedSymbols.slice(0, 12).join(", ") || "none"}.
        </p>
        <div className="preset-refresh-summary">
          <span>
            Refresh {refreshEnabled === false ? "disabled" : "enabled"}.
          </span>
          <span>Cadence {String(refreshCadence ?? 24)}h.</span>
          <span>Stale after {String(staleAfter ?? 168)}h.</span>
        </div>
        {presetMetadata.length ? (
          <Disclosure title={`View ${presetMetadata.length} preset snapshots`}>
            <div className="preset-metadata-list" aria-label="Preset membership snapshots">
              {presetMetadata.map((preset) => (
                <div key={preset.presetName}>
                  <strong>{preset.presetName}</strong>
                  <span>{preset.symbolCount} symbols</span>
                  <span>{preset.status}</span>
                  <span>{preset.source}</span>
                  <span>{formatPresetAge(preset.ageHours)}</span>
                </div>
              ))}
            </div>
          </Disclosure>
        ) : null}
        <button className="button primary" type="submit">
          Save stock universe
        </button>
      </form>
      <Disclosure title="Advanced Path-Based Editor">
        <form className="form-stack" onSubmit={onSubmit}>
          <div>
            <p className="section-label">Advanced setting editor</p>
            <h3>Path-based config update</h3>
            <p className="panel-note">
              Use this editor for less common settings. Common live, venue, risk, model, and
              notification settings are grouped above.
            </p>
          </div>
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
      </Disclosure>
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
): { ok: true; value: ConfigValue } | { ok: false; message: string } {
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

function parsePresetList(value: string): { ok: true; value: string[] } | { ok: false; message: string } {
  const parsed = parseListInput(value, { allowEmpty: true, uppercase: false });
  if (!parsed.ok) {
    return parsed;
  }
  return {
    ok: true,
    value: parsed.value.map((preset) => preset.toLowerCase().replace(/\s+/g, "_")),
  };
}

function parseSymbols(
  value: string,
  options: { allowEmpty: boolean } = { allowEmpty: false },
): { ok: true; value: string[] } | { ok: false; message: string } {
  return parseListInput(value, { allowEmpty: options.allowEmpty, uppercase: true });
}

function parseListInput(
  value: string,
  options: { allowEmpty: boolean; uppercase: boolean },
): { ok: true; value: string[] } | { ok: false; message: string } {
  const trimmed = value.trim();
  if (!trimmed) {
    return options.allowEmpty ? { ok: true, value: [] } : { ok: false, message: "At least one value is required" };
  }
  let values: string[];
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (!Array.isArray(parsed)) {
        return { ok: false, message: "JSON input must be an array" };
      }
      values = parsed.map((item) => String(item));
    } catch {
      return { ok: false, message: "JSON input is not valid" };
    }
  } else {
    values = trimmed.split(/[\s,]+/);
  }
  const normalized = Array.from(
    new Set(
      values
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => (options.uppercase ? item.toUpperCase() : item.toLowerCase())),
    ),
  );
  if (normalized.length === 0 && !options.allowEmpty) {
    return { ok: false, message: "At least one value is required" };
  }
  return { ok: true, value: normalized };
}

function parseCustomPresets(
  value: string,
): { ok: true; value: Record<string, string[]> } | { ok: false; message: string } {
  const trimmed = value.trim();
  if (!trimmed) {
    return { ok: true, value: {} };
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!isPlainObject(parsed)) {
      return { ok: false, message: "Custom presets must be a JSON object" };
    }
    const normalized: Record<string, string[]> = {};
    for (const [name, symbols] of Object.entries(parsed)) {
      if (!Array.isArray(symbols)) {
        return { ok: false, message: "Each custom preset must be a symbol array" };
      }
      const presetName = name.trim().toLowerCase().replace(/\s+/g, "_");
      if (!presetName) {
        return { ok: false, message: "Custom preset names cannot be empty" };
      }
      normalized[presetName] = Array.from(
        new Set(symbols.map((symbol) => String(symbol).trim().toUpperCase()).filter(Boolean)),
      );
    }
    return { ok: true, value: normalized };
  } catch {
    return { ok: false, message: "Custom presets JSON is not valid" };
  }
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

function formatSymbolList(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  return value.map((symbol) => String(symbol).trim().toUpperCase()).filter(Boolean).join(", ");
}

function formatPresetList(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  return value.map((preset) => String(preset).trim().toLowerCase()).filter(Boolean).join(", ");
}

function symbolsFromValue(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((symbol) => String(symbol).trim().toUpperCase()).filter(Boolean);
}

function presetMetadataFromValue(value: unknown): PresetMetadata[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (!isPlainObject(item)) {
        return null;
      }
      return {
        presetName: String(item.presetName ?? ""),
        status: String(item.status ?? ""),
        source: String(item.source ?? ""),
        symbolCount: Number(item.symbolCount ?? 0),
        snapshotSymbolCount: Number(item.snapshotSymbolCount ?? 0),
        customSymbolCount: Number(item.customSymbolCount ?? 0),
        refreshedAt: typeof item.refreshedAt === "string" ? item.refreshedAt : null,
        ageHours: Number.isFinite(Number(item.ageHours)) ? Number(item.ageHours) : null,
        message: typeof item.message === "string" ? item.message : null,
      };
    })
    .filter((item): item is PresetMetadata => Boolean(item && item.presetName));
}

function formatPresetAge(ageHours: number | null | undefined): string {
  if (ageHours === null || ageHours === undefined) {
    return "age unknown";
  }
  if (ageHours < 1) {
    return "fresh";
  }
  if (ageHours < 48) {
    return `${ageHours}h old`;
  }
  return `${Math.floor(ageHours / 24)}d old`;
}

function pathRequiresJson(path: AllowedConfigPath): boolean {
  return (
    path === "alpaca.symbol_universe" ||
    path === "alpaca.symbol_presets" ||
    path === "alpaca.custom_symbols" ||
    path === "alpaca.custom_presets" ||
    path === "alpaca.preset_refresh.sources" ||
    path === "notifications.recipients"
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
