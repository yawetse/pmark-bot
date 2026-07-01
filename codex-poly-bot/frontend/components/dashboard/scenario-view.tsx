"use client";

import {
  ArrowRight,
  Bot,
  CheckCircle2,
  FlaskConical,
  HelpCircle,
  PlayCircle,
  Plus,
  Save,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ManualRunControl,
  type ManualRunResult,
} from "@/components/dashboard/manual-run-control";
import { EmptyState, Message, Panel } from "@/components/dashboard/dashboard-primitives";
import { JsonRecordViewer } from "@/components/dashboard/json-record-viewer";
import { dashboardApi, type ApiClientResult } from "@/lib/api";
import { isAllowedConfigPath, type AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-004, REQ-UI-008, REQ-DAT-008, REQ-OBS-005

type ScenarioSuggestion = {
  title: string;
  body: string;
  configPath: string;
};

type ScenarioStep = {
  key: string;
  label: string;
  status: string;
  state: "ok" | "idle" | "blocked";
  message: string;
  metrics: Record<string, unknown>;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  decisions: Record<string, unknown>;
  recordCount: number;
  records: Array<{ table?: string; id?: string; record?: Record<string, unknown> }>;
  facts: string[];
  suggestions: ScenarioSuggestion[];
  nextStage: {
    state: "ok" | "idle" | "blocked";
    label: string;
    body: string;
  };
};

type ScenarioRun = {
  id: string;
  trigger: string;
  status: string;
  startedAt?: string | null;
  completedAt?: string | null;
};

type ConfigTest = {
  path: string;
  value: string;
  currentValue?: string;
  impact: string;
  recommendation: string;
};

type ScenarioConfigPatch = {
  path: string;
  value: string;
  currentValue?: unknown;
  reason: string;
  expectedImpact: string;
  stage: string;
};

type ScenarioConfigSet = {
  title: string;
  body: string;
  nextStepKey?: string | null;
  runMode?: string | null;
  patches: ScenarioConfigPatch[];
  warnings: string[];
  canApply: boolean;
};

type ScenarioResponse = {
  environment: string;
  generatedAt: string;
  model: string;
  modelMode: string;
  run?: ScenarioRun | null;
  runs: ScenarioRun[];
  selectedStepKey?: string | null;
  steps: ScenarioStep[];
  configTests: ConfigTest[];
  recommendedConfigSet: ScenarioConfigSet;
  answer: {
    title: string;
    body: string;
    bullets: string[];
  };
  message: string;
};

type ScenarioState =
  | { status: "loading" }
  | { status: "ready"; data: ScenarioResponse; configSnapshot: ConfigSnapshot | null }
  | { status: "error"; message: string };

type ConfigDraft = {
  id: string;
  path: string;
  value: string;
};

type ConfigValue = string | boolean | number | string[] | Record<string, unknown>;

type ConfigSnapshot = {
  environment: string;
  username?: string | null;
  config_owner?: string;
  version: string;
  settings: Record<string, unknown>;
};

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
  applies_on_next_loop?: boolean;
};

type SaveState =
  | { status: "idle" }
  | { status: "submitting"; label: string }
  | { status: "saved"; label: string }
  | { status: "error"; message: string };

type ScenarioLeverUnit = "count" | "hours" | "percent" | "usd";

type ScenarioLever =
  | {
      kind: "range";
      path: AllowedConfigPath;
      label: string;
      description: string;
      stage: string;
      fallback: number;
      min: number;
      max: number;
      step: number;
      unit: ScenarioLeverUnit;
      displayMultiplier?: number;
    }
  | {
      kind: "switch";
      path: AllowedConfigPath;
      label: string;
      description: string;
      stage: string;
      fallback: boolean;
    };

type LeverRow = {
  path: AllowedConfigPath;
  label: string;
  description: string;
  stage: string;
  currentValue: ConfigValue;
  nextValue: ConfigValue;
  currentDisplay: string;
  nextDisplay: string;
  changed: boolean;
};

const SCENARIO_LEVERS: ScenarioLever[] = [
  {
    kind: "switch",
    path: "venues.polymarket_us.enabled",
    label: "Polymarket US",
    description: "Allows Polymarket US markets to enter the tick.",
    stage: "Venue",
    fallback: false,
  },
  {
    kind: "range",
    path: "scanner.polymarket.market_data_limit",
    label: "Markets pulled",
    description: "How many active Polymarket markets are fetched before filters run.",
    stage: "Market data",
    fallback: 100,
    min: 1,
    max: 250,
    step: 1,
    unit: "count",
  },
  {
    kind: "range",
    path: "scanner.polymarket.min_liquidity",
    label: "Minimum liquidity",
    description: "Lower this to let thinner order books reach later checks.",
    stage: "Scanner",
    fallback: 500,
    min: 0,
    max: 5000,
    step: 50,
    unit: "usd",
  },
  {
    kind: "range",
    path: "scanner.polymarket.min_depth",
    label: "Minimum depth",
    description: "Lower this to allow smaller bid or ask books.",
    stage: "Scanner",
    fallback: 500,
    min: 0,
    max: 5000,
    step: 50,
    unit: "count",
  },
  {
    kind: "range",
    path: "scanner.polymarket.max_spread",
    label: "Maximum spread",
    description: "Raise this to diagnose wider bid/ask markets.",
    stage: "Scanner",
    fallback: 0.05,
    min: 0.005,
    max: 0.2,
    step: 0.005,
    unit: "percent",
    displayMultiplier: 100,
  },
  {
    kind: "range",
    path: "scanner.polymarket.max_hours_to_resolution",
    label: "Resolution window",
    description: "Raise this to include markets that resolve farther out.",
    stage: "Scanner",
    fallback: 168,
    min: 1,
    max: 720,
    step: 12,
    unit: "hours",
  },
  {
    kind: "range",
    path: "reasoning.polymarket.min_confidence",
    label: "Model confidence",
    description: "Lower this to diagnose candidates the model scores with less certainty.",
    stage: "Reasoning",
    fallback: 0.75,
    min: 0.3,
    max: 0.95,
    step: 0.01,
    unit: "percent",
    displayMultiplier: 100,
  },
  {
    kind: "range",
    path: "reasoning.polymarket.min_edge",
    label: "Minimum edge",
    description: "Lower this to allow smaller probability gaps into strategy checks.",
    stage: "Reasoning",
    fallback: 0.07,
    min: 0.005,
    max: 0.25,
    step: 0.005,
    unit: "percent",
    displayMultiplier: 100,
  },
  {
    kind: "range",
    path: "risk.polymarket.max_position_usd",
    label: "Max position",
    description: "Raise this only for dry-run diagnosis of risk gate blocks.",
    stage: "Risk",
    fallback: 25,
    min: 1,
    max: 250,
    step: 1,
    unit: "usd",
  },
];

export function ScenarioView() {
  const [state, setState] = useState<ScenarioState>({ status: "loading" });
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedStepKey, setSelectedStepKey] = useState("");
  const [prompt, setPrompt] = useState("");
  const [leverDrafts, setLeverDrafts] = useState<Record<string, ConfigValue>>({});
  const [configDrafts, setConfigDrafts] = useState<ConfigDraft[]>([]);
  const [actionState, setActionState] = useState<"idle" | "running">("idle");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  useEffect(() => {
    void loadScenario({});
  }, []);

  const selectedStep = useMemo(() => {
    if (state.status !== "ready") {
      return null;
    }
    return (
      state.data.steps.find((step) => step.key === selectedStepKey) ??
      state.data.steps.find((step) => step.key === state.data.selectedStepKey) ??
      state.data.steps[0] ??
      null
    );
  }, [selectedStepKey, state]);

  const leverRows = useMemo(() => {
    if (state.status !== "ready") {
      return [];
    }
    return SCENARIO_LEVERS.map((lever) => leverRow(lever, state.configSnapshot?.settings ?? {}, leverDrafts));
  }, [leverDrafts, state]);

  const changedLeverRows = useMemo(
    () => leverRows.filter((row) => row.changed),
    [leverRows],
  );

  async function loadScenario({
    runId = selectedRunId,
    stepKey = selectedStepKey,
    nextPrompt = prompt,
    configOverrides = [],
  }: {
    runId?: string;
    stepKey?: string;
    nextPrompt?: string;
    configOverrides?: Array<{ path: string; value: string }>;
  }) {
    setActionState("running");
    const [result, configSnapshot] = await Promise.all([
      dashboardApi<ScenarioResponse>("scenario/analyze", {
        method: "POST",
        body: JSON.stringify({
          runId: runId || null,
          stepKey: stepKey || null,
          prompt: nextPrompt || null,
          configOverrides,
        }),
      }),
      dashboardApi<ConfigSnapshot>("config/current"),
    ]);
    setActionState("idle");
    if (!result.ok) {
      setState({ status: "error", message: result.message });
      return;
    }
    setState({
      status: "ready",
      data: result.data,
      configSnapshot: configSnapshot.ok ? configSnapshot.data : null,
    });
    setSelectedRunId(result.data.run?.id ?? "");
    setSelectedStepKey(result.data.selectedStepKey ?? result.data.steps[0]?.key ?? "");
  }

  function onPromptSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadScenario({ nextPrompt: prompt, stepKey: selectedStep?.key ?? selectedStepKey });
  }

  function onConfigSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const scenarioDrafts = scenarioDraftsFromRows(changedLeverRows);
    if (!scenarioDrafts.length) {
      setSaveState({ status: "error", message: "Move at least one lever, then analyze the scenario." });
      return;
    }
    void loadScenario({
      stepKey: selectedStep?.key ?? selectedStepKey,
      configOverrides: scenarioDrafts,
    });
  }

  function onManualRunAccepted(result: ManualRunResult) {
    void loadScenario({ runId: result.runId, stepKey: "" });
  }

  function addConfigDraft() {
    setConfigDrafts((drafts) => [
      ...drafts,
      {
        id: `config-draft-${Date.now()}`,
        path: "scanner.polymarket.max_hours_to_resolution",
        value: "336",
      },
    ]);
  }

  function updateConfigDraft(id: string, field: "path" | "value", value: string) {
    setConfigDrafts((drafts) =>
      drafts.map((draft) => (draft.id === id ? { ...draft, [field]: value } : draft)),
    );
  }

  function removeConfigDraft(id: string) {
    setConfigDrafts((drafts) => drafts.filter((draft) => draft.id !== id));
  }

  function loadAiConfigSet() {
    if (state.status !== "ready" || !state.data.recommendedConfigSet.patches.length) {
      return;
    }
    const nextLeverDrafts: Record<string, ConfigValue> = {};
    const advancedDrafts: ConfigDraft[] = [];
    for (const [index, patch] of state.data.recommendedConfigSet.patches.entries()) {
      if (SCENARIO_LEVERS.some((lever) => lever.path === patch.path)) {
        nextLeverDrafts[patch.path] = parseScenarioDraftValue(patch.value);
      } else {
        advancedDrafts.push({
          id: `ai-config-${index}-${patch.path}`,
          path: patch.path,
          value: formatDraftValue(patch.value),
        });
      }
    }
    setLeverDrafts((currentDrafts) => ({ ...currentDrafts, ...nextLeverDrafts }));
    setConfigDrafts(advancedDrafts);
    setSaveState({ status: "idle" });
  }

  async function applyAiConfigSet() {
    if (state.status !== "ready") {
      return;
    }
    await saveConfigDrafts(
      state.data.recommendedConfigSet.patches.map((patch) => ({
        path: patch.path,
        value: formatDraftValue(patch.value),
      })),
      "AI settings applied",
    );
  }

  async function applyTestConfig() {
    const drafts = [...scenarioDraftsFromRows(changedLeverRows), ...configDrafts];
    await saveConfigDrafts(drafts, "Scenario settings applied");
  }

  async function saveConfigDrafts(
    drafts: Array<{ path: string; value: string }>,
    savedLabel: string,
  ): Promise<boolean> {
    const parsed = parseConfigDrafts(drafts);
    if (!parsed.ok) {
      setSaveState({ status: "error", message: parsed.message });
      return false;
    }
    if (!parsed.patches.length) {
      setSaveState({ status: "error", message: "Add at least one setting before applying." });
      return false;
    }

    setSaveState({ status: "submitting", label: savedLabel });
    const snapshot = await dashboardApi<ConfigSnapshot>("config/current");
    if (!snapshot.ok) {
      setSaveState({ status: "error", message: snapshot.message });
      return false;
    }

    const firstAttempt = await submitConfigPatches(snapshot.data, parsed.patches);
    if (!firstAttempt.result.ok && firstAttempt.result.status === 409) {
      const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
      if (!refreshed.ok) {
        setSaveState({ status: "error", message: "Config changed and could not be refreshed." });
        return false;
      }
      const retry = await submitConfigPatches(refreshed.data, parsed.patches);
      return finalizeConfigSave(retry, savedLabel);
    }
    return finalizeConfigSave(firstAttempt, savedLabel);
  }

  async function submitConfigPatches(
    snapshot: ConfigSnapshot,
    patches: Array<{ path: AllowedConfigPath; value: ConfigValue }>,
  ): Promise<{
    result: ApiClientResult<ConfigUpdateResponse>;
    requestedVersion: string;
  }> {
    const requestedVersion = nextConfigVersion(snapshot.version);
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: snapshot.environment,
        version: requestedVersion,
        expected_version: expectedVersionFromSnapshot(snapshot) || null,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
      }),
    });
    return { result, requestedVersion };
  }

  function finalizeConfigSave(
    attempt: {
      result: ApiClientResult<ConfigUpdateResponse>;
      requestedVersion: string;
    },
    savedLabel: string,
  ): boolean {
    if (!attempt.result.ok) {
      setSaveState({ status: "error", message: readableConfigError(attempt.result.message) });
      return false;
    }
    setSaveState({ status: "saved", label: savedLabel });
    return true;
  }

  if (state.status === "loading") {
    return (
      <section className="operator-panel">
        <p className="section-label">Scenario</p>
        <h1>Tick Walkthrough</h1>
        <p className="panel-note">Loading the latest tick.</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="operator-panel">
        <p className="section-label">Scenario</p>
        <h1>Tick Walkthrough</h1>
        <Message tone="blocked">{state.message}</Message>
      </section>
    );
  }

  return (
    <div className="page-stack scenario-view">
      <section className="operator-panel scenario-hero-panel">
        <div className="panel-heading">
          <div>
            <p className="section-label">Scenario</p>
            <h1>Scenario Lab</h1>
          </div>
          <span className="status idle">{state.data.model}</span>
        </div>
        <p className="panel-note">{state.data.message}</p>
        <div className="scenario-selector-row">
          <label>
            Tick data
            <select
              value={selectedRunId}
              onChange={(event) => {
                setSelectedRunId(event.target.value);
                setSelectedStepKey("");
              }}
            >
              <option value="">Latest tick</option>
              {state.data.runs.length ? null : <option value="">No runs recorded</option>}
              {state.data.runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.status} - {run.trigger} - {formatDateTime(run.completedAt ?? run.startedAt)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button primary"
            disabled={actionState === "running"}
            type="button"
            onClick={() => void loadScenario({ runId: selectedRunId, stepKey: selectedStepKey })}
          >
            <PlayCircle aria-hidden="true" size={16} />
            Analyze
          </button>
        </div>
        <div className="scenario-summary-strip" aria-label="Current scenario summary">
          <ScenarioSummaryItem label="Tick" value={state.data.run?.status ?? "No tick"} />
          <ScenarioSummaryItem label="Trigger" value={state.data.run?.trigger ?? "None"} />
          <ScenarioSummaryItem label="Gate" value={selectedStep?.label ?? "No step"} />
          <ScenarioSummaryItem
            label="Config"
            value={state.configSnapshot?.username || state.configSnapshot?.config_owner || "user"}
          />
        </div>
      </section>

      <ManualRunControl environment={state.data.environment} onAccepted={onManualRunAccepted} />

      {state.data.steps.length ? (
        <div className="scenario-layout">
          <Panel eyebrow="Walkthrough" title="Five steps" className="scenario-step-panel">
            <div className="scenario-step-list">
              {state.data.steps.map((step) => (
                <button
                  className="scenario-step-button"
                  data-active={step.key === selectedStep?.key ? "true" : undefined}
                  key={step.key}
                  type="button"
                  onClick={() => {
                    setSelectedStepKey(step.key);
                    void loadScenario({ runId: selectedRunId, stepKey: step.key });
                  }}
                >
                  <span className={`status-dot ${step.state}`} aria-hidden="true" />
                  <span>
                    <strong>{step.label}</strong>
                    <small>{step.status}</small>
                  </span>
                  <HelpCircle aria-hidden="true" size={16} />
                </button>
              ))}
            </div>
          </Panel>

          {selectedStep ? (
            <Panel
              eyebrow="Step detail"
              title={selectedStep.label}
              status={selectedStep.status}
              statusTone={selectedStep.state}
              className="scenario-detail-panel"
            >
              <p className="panel-note">{selectedStep.message}</p>
              <div className="scenario-next-stage">
                <span className={`status-dot ${selectedStep.nextStage.state}`} aria-hidden="true" />
                <div>
                  <strong>{selectedStep.nextStage.label}</strong>
                  <p>{selectedStep.nextStage.body}</p>
                </div>
              </div>
              <div className="scenario-columns">
                <ScenarioList title="Facts" items={selectedStep.facts} />
                <section>
                  <h3>Suggestions</h3>
                  <div className="scenario-suggestion-list">
                    {selectedStep.suggestions.map((suggestion) => (
                      <article key={`${selectedStep.key}-${suggestion.title}`}>
                        <strong>{suggestion.title}</strong>
                        <p>{suggestion.body}</p>
                        <small>{suggestion.configPath}</small>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
              <details className="scenario-records">
                <summary>Linked records ({selectedStep.recordCount})</summary>
                <JsonRecordViewer
                  data={selectedStep.records}
                  label={`Linked records for ${selectedStep.label}`}
                />
              </details>
            </Panel>
          ) : null}
        </div>
      ) : (
        <EmptyState
          title="No tick recorded"
          body="Run a manual data import, scanner-only run, or full dry run to create a scenario walkthrough."
        />
      )}

      <Panel eyebrow="Levers" title="Move settings to test a pass path" className="scenario-lever-panel">
        <form className="scenario-form" onSubmit={onConfigSubmit}>
          <div className="scenario-lever-grid">
            {SCENARIO_LEVERS.map((lever) => (
              <ScenarioLeverControl
                key={lever.path}
                lever={lever}
                row={leverRows.find((item) => item.path === lever.path)}
                value={leverDrafts[lever.path]}
                onChange={(value) => {
                  setLeverDrafts((currentDrafts) => ({ ...currentDrafts, [lever.path]: value }));
                  setSaveState({ status: "idle" });
                }}
              />
            ))}
          </div>
          <div className="scenario-config-actions">
            <button className="button" type="button" onClick={loadAiConfigSet}>
              <Sparkles aria-hidden="true" size={16} />
              Use recommended
            </button>
            <button className="button" disabled={actionState === "running"} type="submit">
              <FlaskConical aria-hidden="true" size={16} />
              Analyze scenario
            </button>
            <button
              className="button primary"
              disabled={saveState.status === "submitting" || !changedLeverRows.length}
              type="button"
              onClick={() => void applyTestConfig()}
            >
              <Save aria-hidden="true" size={16} />
              Apply scenario settings
            </button>
          </div>
        </form>
        <SaveStatus state={saveState} />
      </Panel>

      <ScenarioBeforeAfter
        configTests={state.data.configTests}
        generatedAt={state.data.generatedAt}
        leverRows={leverRows}
        run={state.data.run}
        selectedStep={selectedStep}
      />

      <div className="scenario-help-grid">
        <Panel eyebrow="Recommended path" title="Suggested next move">
          <ScenarioConfigPlan
            configSet={state.data.recommendedConfigSet}
            onApply={applyAiConfigSet}
            onLoad={loadAiConfigSet}
            disabled={actionState === "running" || saveState.status === "submitting"}
          />
          <div className="scenario-answer">
            <strong>{state.data.answer.title}</strong>
            <p>{state.data.answer.body}</p>
            <ul>
              {state.data.answer.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel eyebrow="Ask" title="Ask about this tick">
          <form className="scenario-form" onSubmit={onPromptSubmit}>
            <label>
              Question
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={4}
                placeholder="What setting is blocking this trade?"
              />
            </label>
            <button className="button primary" disabled={actionState === "running"} type="submit">
              <Bot aria-hidden="true" size={16} />
              Ask
            </button>
          </form>
        </Panel>
      </div>

      <details className="scenario-advanced-editor">
        <summary>
          <Settings2 aria-hidden="true" size={16} />
          Advanced path editor
        </summary>
        <Panel eyebrow="Advanced" title="Test a specific config path">
          <form
            className="scenario-form"
            onSubmit={(event) => {
              event.preventDefault();
              void loadScenario({
                stepKey: selectedStep?.key ?? selectedStepKey,
                configOverrides: configDrafts
                  .map((draft) => ({ path: draft.path.trim(), value: draft.value.trim() }))
                  .filter((draft) => draft.path),
              });
            }}
          >
            {configDrafts.map((draft) => (
              <div className="scenario-config-row" key={draft.id}>
                <label>
                  Config path
                  <input
                    value={draft.path}
                    onChange={(event) => updateConfigDraft(draft.id, "path", event.target.value)}
                  />
                </label>
                <label>
                  Test value
                  <input
                    value={draft.value}
                    onChange={(event) => updateConfigDraft(draft.id, "value", event.target.value)}
                  />
                </label>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => removeConfigDraft(draft.id)}
                  aria-label="Remove setting"
                >
                  <Trash2 aria-hidden="true" size={16} />
                </button>
              </div>
            ))}
            <div className="scenario-config-actions">
              <button className="button" type="button" onClick={addConfigDraft}>
                <Plus aria-hidden="true" size={16} />
                Add setting
              </button>
              <button className="button" disabled={!configDrafts.length || actionState === "running"} type="submit">
                <FlaskConical aria-hidden="true" size={16} />
                Test path
              </button>
            </div>
          </form>
        </Panel>
      </details>
    </div>
  );
}

function ScenarioSummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ScenarioLeverControl({
  lever,
  onChange,
  row,
}: {
  lever: ScenarioLever;
  row?: LeverRow;
  value?: ConfigValue;
  onChange: (value: ConfigValue) => void;
}) {
  const currentDisplay = row?.currentDisplay ?? formatLeverDisplay(lever, lever.fallback);
  const nextDisplay = row?.nextDisplay ?? currentDisplay;
  if (lever.kind === "switch") {
    const checked = Boolean(row?.nextValue ?? lever.fallback);
    return (
      <article className="scenario-lever-card" data-changed={row?.changed ? "true" : undefined}>
        <div className="scenario-lever-heading">
          <div>
            <span>{lever.stage}</span>
            <strong>{lever.label}</strong>
          </div>
          <button
            aria-checked={checked}
            className="scenario-switch"
            role="switch"
            type="button"
            onClick={() => onChange(!checked)}
          >
            <span aria-hidden="true" />
          </button>
        </div>
        <p>{lever.description}</p>
        <div className="scenario-lever-values">
          <span>Current {currentDisplay}</span>
          <strong>Scenario {nextDisplay}</strong>
        </div>
      </article>
    );
  }

  const value = Number(row?.nextValue ?? lever.fallback);
  return (
    <article className="scenario-lever-card" data-changed={row?.changed ? "true" : undefined}>
      <div className="scenario-lever-heading">
        <div>
          <span>{lever.stage}</span>
          <strong>{lever.label}</strong>
        </div>
        {row?.changed ? <CheckCircle2 aria-label="Changed" size={17} /> : null}
      </div>
      <p>{lever.description}</p>
      <input
        aria-label={lever.label}
        max={lever.max}
        min={lever.min}
        step={lever.step}
        type="range"
        value={value}
        onChange={(event) => onChange(roundLeverNumber(Number(event.target.value), lever.step))}
      />
      <div className="scenario-lever-values">
        <span>Current {currentDisplay}</span>
        <strong>Scenario {nextDisplay}</strong>
      </div>
    </article>
  );
}

function ScenarioBeforeAfter({
  configTests,
  generatedAt,
  leverRows,
  run,
  selectedStep,
}: {
  configTests: ConfigTest[];
  generatedAt: string;
  leverRows: LeverRow[];
  run?: ScenarioRun | null;
  selectedStep: ScenarioStep | null;
}) {
  const changedRows = leverRows.filter((row) => row.changed);
  const rowsForCurrent = changedRows.length ? changedRows : leverRows.slice(0, 5);
  const testByPath = new Map(configTests.map((test) => [test.path, test]));

  return (
    <section className="scenario-before-after" aria-label="Scenario before and after">
      <article>
        <div className="scenario-card-heading">
          <PlayCircle aria-hidden="true" size={18} />
          <div>
            <span>Tick</span>
            <strong>{run?.status ?? "No tick selected"}</strong>
          </div>
        </div>
        <dl>
          <div>
            <dt>Trigger</dt>
            <dd>{run?.trigger ?? "None"}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{formatDateTime(run?.startedAt)}</dd>
          </div>
          <div>
            <dt>Analyzed</dt>
            <dd>{formatDateTime(generatedAt)}</dd>
          </div>
          <div>
            <dt>Gate</dt>
            <dd>{selectedStep ? `${selectedStep.label}: ${selectedStep.status}` : "No step"}</dd>
          </div>
        </dl>
      </article>

      <article>
        <div className="scenario-card-heading">
          <SlidersHorizontal aria-hidden="true" size={18} />
          <div>
            <span>Current settings</span>
            <strong>{changedRows.length ? `${changedRows.length} selected` : "Baseline"}</strong>
          </div>
        </div>
        <div className="scenario-setting-list">
          {rowsForCurrent.map((row) => (
            <div key={`current-${row.path}`}>
              <span>{row.label}</span>
              <strong>{row.currentDisplay}</strong>
            </div>
          ))}
        </div>
      </article>

      <article>
        <div className="scenario-card-heading">
          <ArrowRight aria-hidden="true" size={18} />
          <div>
            <span>Scenario</span>
            <strong>{changedRows.length ? "After changes" : "No changes yet"}</strong>
          </div>
        </div>
        {changedRows.length ? (
          <div className="scenario-setting-list">
            {changedRows.map((row) => {
              const test = testByPath.get(row.path);
              return (
                <div key={`after-${row.path}`}>
                  <span>{row.label}</span>
                  <strong>
                    {row.currentDisplay} <ArrowRight aria-hidden="true" size={13} /> {row.nextDisplay}
                  </strong>
                  <small>{test?.impact ?? row.description}</small>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="panel-note">Move a lever, then analyze the scenario to compare the pass path.</p>
        )}
      </article>
    </section>
  );
}

function ScenarioConfigPlan({
  configSet,
  disabled,
  onApply,
  onLoad,
}: {
  configSet: ScenarioConfigSet;
  disabled: boolean;
  onApply: () => void;
  onLoad: () => void;
}) {
  return (
    <div className="scenario-config-plan">
      <div className="scenario-plan-heading">
        <div>
          <strong>{configSet.title}</strong>
          <p>{configSet.body}</p>
        </div>
        {configSet.runMode ? <span className="status waiting">{configSet.runMode}</span> : null}
      </div>
      {configSet.patches.length ? (
        <div className="scenario-plan-patches">
          {configSet.patches.map((patch) => (
            <article key={`${patch.path}-${patch.value}`}>
              <strong>{patch.path}</strong>
              <small>
                {formatDraftValue(patch.currentValue)} to {patch.value}
              </small>
              <p>{patch.reason}</p>
              <p>{patch.expectedImpact}</p>
            </article>
          ))}
        </div>
      ) : null}
      {configSet.warnings.length ? (
        <ul className="scenario-plan-warnings">
          {configSet.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      <div className="scenario-config-actions">
        <button
          className="button"
          disabled={disabled || !configSet.patches.length}
          type="button"
          onClick={onLoad}
        >
          <FlaskConical aria-hidden="true" size={16} />
          Load settings
        </button>
        <button
          className="button primary"
          disabled={disabled || !configSet.canApply}
          type="button"
          onClick={onApply}
        >
          <Save aria-hidden="true" size={16} />
          Apply AI settings
        </button>
      </div>
    </div>
  );
}

function SaveStatus({ state }: { state: SaveState }) {
  if (state.status === "idle") {
    return null;
  }
  if (state.status === "submitting") {
    return <Message tone="waiting">Saving {state.label}...</Message>;
  }
  if (state.status === "saved") {
    return <Message tone="ok">{state.label}. Settings apply on the next loop.</Message>;
  }
  return <Message tone="blocked">{state.message}</Message>;
}

function ScenarioList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h3>{title}</h3>
      <ul className="scenario-fact-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function leverRow(
  lever: ScenarioLever,
  settings: Record<string, unknown>,
  drafts: Record<string, ConfigValue>,
): LeverRow {
  const currentValue = coerceLeverValue(lever, valueAtPath(settings, lever.path));
  const nextValue = coerceLeverValue(
    lever,
    Object.prototype.hasOwnProperty.call(drafts, lever.path) ? drafts[lever.path] : currentValue,
  );
  return {
    path: lever.path,
    label: lever.label,
    description: lever.description,
    stage: lever.stage,
    currentValue,
    nextValue,
    currentDisplay: formatLeverDisplay(lever, currentValue),
    nextDisplay: formatLeverDisplay(lever, nextValue),
    changed: !sameConfigValue(currentValue, nextValue),
  };
}

function coerceLeverValue(lever: ScenarioLever, rawValue: unknown): ConfigValue {
  if (lever.kind === "switch") {
    if (typeof rawValue === "boolean") {
      return rawValue;
    }
    if (typeof rawValue === "string") {
      return rawValue.toLowerCase() === "true";
    }
    return lever.fallback;
  }
  const numericValue = Number(rawValue ?? lever.fallback);
  if (!Number.isFinite(numericValue)) {
    return lever.fallback;
  }
  return clamp(roundLeverNumber(numericValue, lever.step), lever.min, lever.max);
}

function scenarioDraftsFromRows(rows: LeverRow[]): Array<{ path: string; value: string }> {
  return rows
    .filter((row) => row.changed)
    .map((row) => ({ path: row.path, value: formatDraftValue(row.nextValue) }));
}

function parseScenarioDraftValue(value: string): ConfigValue {
  const parsed = parseConfigValue(value);
  return parsed.ok ? parsed.value : value;
}

function valueAtPath(source: Record<string, unknown>, path: string): unknown {
  let current: unknown = source;
  for (const part of path.split(".")) {
    if (!isPlainObject(current) || !(part in current)) {
      return undefined;
    }
    current = current[part];
  }
  return current;
}

function formatLeverDisplay(lever: ScenarioLever, value: ConfigValue): string {
  if (lever.kind === "switch") {
    return value ? "On" : "Off";
  }
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return String(value);
  }
  if (lever.unit === "percent") {
    return `${formatNumber(numericValue * (lever.displayMultiplier ?? 100))}%`;
  }
  if (lever.unit === "usd") {
    return `$${formatNumber(numericValue)}`;
  }
  if (lever.unit === "hours") {
    return `${formatNumber(numericValue)}h`;
  }
  return formatNumber(numericValue);
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value < 1 ? 2 : 1,
    minimumFractionDigits: 0,
  }).format(value);
}

function sameConfigValue(left: ConfigValue, right: ConfigValue): boolean {
  if (typeof left === "boolean" || typeof right === "boolean") {
    return left === right;
  }
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return Math.abs(leftNumber - rightNumber) < 0.000001;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

function roundLeverNumber(value: number, step: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  const decimals = String(step).includes(".") ? String(step).split(".")[1].length : 0;
  return Number(value.toFixed(Math.max(decimals, 0)));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function parseConfigDrafts(
  drafts: Array<{ path: string; value: string }>,
):
  | { ok: true; patches: Array<{ path: AllowedConfigPath; value: ConfigValue }> }
  | { ok: false; message: string } {
  const patches: Array<{ path: AllowedConfigPath; value: ConfigValue }> = [];
  for (const draft of drafts) {
    const path = draft.path.trim();
    if (!path) {
      continue;
    }
    if (!isAllowedConfigPath(path)) {
      return { ok: false, message: `${path} is not a supported dashboard config path.` };
    }
    const parsed = parseConfigValue(draft.value);
    if (!parsed.ok) {
      return { ok: false, message: `${path}: ${parsed.message}` };
    }
    patches.push({ path, value: parsed.value });
  }
  return { ok: true, patches };
}

function parseConfigValue(value: string): { ok: true; value: ConfigValue } | { ok: false; message: string } {
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

function formatDraftValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nextConfigVersion(currentVersion: string): string {
  const match = /^v(\d+)$/.exec(currentVersion);
  if (match) {
    return `v${Number(match[1]) + 1}`;
  }
  return `ui-${Date.now()}`;
}

function expectedVersionFromSnapshot(snapshot: ConfigSnapshot): string {
  return snapshot.version === "bootstrap" ? "" : snapshot.version;
}

function readableConfigError(message: string): string {
  try {
    const parsed = JSON.parse(message) as { message?: string };
    return parsed.message ?? message;
  } catch {
    return message;
  }
}
