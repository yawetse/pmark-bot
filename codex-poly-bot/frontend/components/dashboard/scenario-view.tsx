"use client";

import { Bot, FlaskConical, HelpCircle, PlayCircle } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ManualRunControl,
  type ManualRunResult,
} from "@/components/dashboard/manual-run-control";
import { EmptyState, Message, Panel } from "@/components/dashboard/dashboard-primitives";
import { dashboardApi } from "@/lib/api";

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
  impact: string;
  recommendation: string;
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
  answer: {
    title: string;
    body: string;
    bullets: string[];
  };
  message: string;
};

type ScenarioState =
  | { status: "loading" }
  | { status: "ready"; data: ScenarioResponse }
  | { status: "error"; message: string };

export function ScenarioView() {
  const [state, setState] = useState<ScenarioState>({ status: "loading" });
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedStepKey, setSelectedStepKey] = useState("");
  const [prompt, setPrompt] = useState("");
  const [configPath, setConfigPath] = useState("scanner.polymarket.max_spread");
  const [configValue, setConfigValue] = useState("0.08");
  const [actionState, setActionState] = useState<"idle" | "running">("idle");

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
    const result = await dashboardApi<ScenarioResponse>("scenario/analyze", {
      method: "POST",
      body: JSON.stringify({
        runId: runId || null,
        stepKey: stepKey || null,
        prompt: nextPrompt || null,
        configOverrides,
      }),
    });
    setActionState("idle");
    if (!result.ok) {
      setState({ status: "error", message: result.message });
      return;
    }
    setState({ status: "ready", data: result.data });
    setSelectedRunId(result.data.run?.id ?? "");
    setSelectedStepKey(result.data.selectedStepKey ?? result.data.steps[0]?.key ?? "");
  }

  function onPromptSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadScenario({ nextPrompt: prompt, stepKey: selectedStep?.key ?? selectedStepKey });
  }

  function onConfigSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadScenario({
      stepKey: selectedStep?.key ?? selectedStepKey,
      configOverrides: [{ path: configPath, value: configValue }],
    });
  }

  function onManualRunAccepted(result: ManualRunResult) {
    void loadScenario({ runId: result.runId, stepKey: "" });
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
      <section className="operator-panel">
        <div className="panel-heading">
          <div>
            <p className="section-label">Scenario</p>
            <h1>Tick Walkthrough</h1>
          </div>
          <span className="status idle">{state.data.model}</span>
        </div>
        <p className="panel-note">{state.data.message}</p>
        <div className="scenario-selector-row">
          <label>
            Tick
            <select
              value={selectedRunId}
              onChange={(event) => {
                setSelectedRunId(event.target.value);
                void loadScenario({ runId: event.target.value, stepKey: "" });
              }}
            >
              {state.data.runs.length ? null : <option value="">No runs recorded</option>}
              {state.data.runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.status} - {run.trigger} - {formatDateTime(run.completedAt ?? run.startedAt)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button"
            disabled={actionState === "running"}
            type="button"
            onClick={() => void loadScenario({ runId: selectedRunId, stepKey: selectedStepKey })}
          >
            <PlayCircle aria-hidden="true" size={16} />
            Refresh
          </button>
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
                <pre>{JSON.stringify(selectedStep.records, null, 2)}</pre>
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

      <div className="scenario-help-grid">
        <Panel eyebrow="Help with AI" title="Ask about this step">
          <form className="scenario-form" onSubmit={onPromptSubmit}>
            <label>
              Prompt
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={4}
                placeholder="Why did this stop before trading?"
              />
            </label>
            <button className="button primary" disabled={actionState === "running"} type="submit">
              <Bot aria-hidden="true" size={16} />
              Help with AI
            </button>
          </form>
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

        <Panel eyebrow="Test config" title="Try an option">
          <form className="scenario-form" onSubmit={onConfigSubmit}>
            <label>
              Config path
              <input value={configPath} onChange={(event) => setConfigPath(event.target.value)} />
            </label>
            <label>
              Test value
              <input value={configValue} onChange={(event) => setConfigValue(event.target.value)} />
            </label>
            <button className="button" disabled={actionState === "running"} type="submit">
              <FlaskConical aria-hidden="true" size={16} />
              Test option
            </button>
          </form>
          <div className="scenario-test-list">
            {state.data.configTests.map((test) => (
              <article key={`${test.path}-${test.value}`}>
                <strong>{test.path || "No path"}</strong>
                <p>{test.impact}</p>
                <small>{test.recommendation}</small>
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
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
