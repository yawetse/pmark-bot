"use client";

import { Bot, Play, Rows3 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { Message, Panel } from "@/components/dashboard/dashboard-primitives";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-004, REQ-DAT-008, REQ-OBS-005

type DataExplorerDataset = {
  id: string;
  label: string;
  table: string;
  description: string;
  rowCount: number;
  columns: string[];
  sampleRows: Record<string, unknown>[];
};

type DataExplorerMetadata = {
  environment: string;
  generatedAt: string;
  defaultQuery: string;
  datasets: DataExplorerDataset[];
};

type DataQueryResult = {
  environment: string;
  generatedAt: string;
  query: string;
  dataset: {
    id: string;
    label: string;
    table: string;
  };
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  totalMatched: number;
  limit: number;
  message: string;
};

type DataQueryAiResult = {
  environment: string;
  generatedAt: string;
  model: string;
  modelMode: string;
  prompt: string;
  query: string;
  explanation: string;
  datasets: string[];
  warnings: string[];
};

type LoadState =
  | { status: "loading" }
  | { status: "ready"; metadata: DataExplorerMetadata; result: DataQueryResult }
  | { status: "error"; message: string };

type AiQueryState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "ready"; result: DataQueryAiResult }
  | { status: "error"; message: string };

const DEFAULT_QUERY = "select * from market_data_pulls limit 25";

export function DataExplorerView() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [selectedDataset, setSelectedDataset] = useState("market_data_pulls");
  const [queryState, setQueryState] = useState<"idle" | "running">("idle");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiState, setAiState] = useState<AiQueryState>({ status: "idle" });

  useEffect(() => {
    let active = true;
    async function load() {
      const metadata = await dashboardApi<DataExplorerMetadata>("data/explorer");
      if (!active) {
        return;
      }
      if (!metadata.ok) {
        setState({ status: "error", message: metadata.message });
        return;
      }
      setQuery(metadata.data.defaultQuery || DEFAULT_QUERY);
      const result = await runQuery(metadata.data.defaultQuery || DEFAULT_QUERY);
      if (!active) {
        return;
      }
      if (!result.ok) {
        setState({ status: "error", message: result.message });
        return;
      }
      setState({ status: "ready", metadata: metadata.data, result: result.data });
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  const resultColumns = useMemo<DashboardGridColumn<Record<string, unknown>>[]>(() => {
    if (state.status !== "ready") {
      return [];
    }
    return state.result.columns.map((column) => ({
      field: column,
      headerName: column,
      minWidth: column === "message" ? 260 : 140,
      valueGetter: (params) => displayCell(params.data?.[column]),
    }));
  }, [state]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await executeQuery(query);
  }

  async function onAiSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAiState({ status: "running" });
    const generated = await dashboardApi<DataQueryAiResult>("data/query/generate", {
      method: "POST",
      body: JSON.stringify({ prompt: aiPrompt }),
    });
    if (!generated.ok) {
      setAiState({ status: "error", message: generated.message });
      return;
    }
    setAiState({ status: "ready", result: generated.data });
    setQuery(generated.data.query);
    if (generated.data.datasets[0]) {
      setSelectedDataset(generated.data.datasets[0]);
    }
    await executeQuery(generated.data.query);
  }

  async function executeQuery(nextQuery: string) {
    setQueryState("running");
    const result = await runQuery(nextQuery);
    setQueryState("idle");
    if (!result.ok) {
      setState((current) =>
        current.status === "ready"
          ? { ...current, result: { ...current.result, message: result.message, rows: [], rowCount: 0, totalMatched: 0 } }
          : { status: "error", message: result.message },
      );
      return;
    }
    setState((current) =>
      current.status === "ready"
        ? { ...current, result: result.data }
        : {
            status: "ready",
            metadata: {
              environment: result.data.environment,
              generatedAt: result.data.generatedAt,
              defaultQuery: DEFAULT_QUERY,
              datasets: [],
            },
            result: result.data,
        },
    );
  }

  async function selectDataset(datasetId: string) {
    if (state.status !== "ready") {
      return;
    }
    const dataset = state.metadata.datasets.find((item) => item.id === datasetId);
    if (!dataset) {
      return;
    }
    setSelectedDataset(dataset.id);
    const nextQuery = `select * from ${dataset.id} limit 25`;
    setQuery(nextQuery);
    await executeQuery(nextQuery);
  }

  if (state.status === "loading") {
    return (
      <section className="operator-panel">
        <p className="section-label">Data</p>
        <h1>Data Explorer</h1>
        <p className="panel-note">Loading available datasets.</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="operator-panel">
        <p className="section-label">Data</p>
        <h1>Data Explorer</h1>
        <Message tone="blocked">{state.message}</Message>
      </section>
    );
  }

  return (
    <div className="page-stack data-explorer">
      <div className="data-explorer-layout">
        <section className="operator-panel data-overview-panel">
          <div className="panel-heading">
            <div>
              <p className="section-label">Data</p>
              <h1>Data Explorer</h1>
            </div>
            <span className="status ok">{state.metadata.environment}</span>
          </div>
          <p className="panel-note">
            Query dashboard datasets with read-only SELECT statements. The workbench only supports known data tables.
          </p>
        </section>

        <Panel eyebrow="Ask with AI" title="Generate SQL" className="data-ai-panel">
          <form className="query-form" onSubmit={onAiSubmit}>
            <label>
              Prompt
              <textarea
                value={aiPrompt}
                onChange={(event) => setAiPrompt(event.target.value)}
                placeholder="Show rejected scanner candidates and refusal reasons"
                rows={5}
              />
            </label>
            <div className="query-actions">
              <button className="button primary" disabled={aiState.status === "running"} type="submit">
                <Bot aria-hidden="true" size={16} />
                {aiState.status === "running" ? "Asking" : "Ask AI"}
              </button>
              <span className="panel-note">Generates read-only SQL across known dashboard datasets.</span>
            </div>
            {aiState.status === "ready" ? (
              <div className="data-ai-answer">
                <strong>Suggested query</strong>
                <p>{aiState.result.explanation}</p>
                <small>{aiState.result.query}</small>
                {aiState.result.warnings.length ? (
                  <ul>
                    {aiState.result.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
            {aiState.status === "error" ? <Message tone="blocked">{aiState.message}</Message> : null}
          </form>
        </Panel>

        <Panel eyebrow="Workbench" title="Query data" className="data-query-panel">
          <form className="query-form" onSubmit={onSubmit}>
            <label>
              SQL
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={5}
                spellCheck={false}
              />
            </label>
            <div className="query-actions">
              <button className="button primary" disabled={queryState === "running"} type="submit">
                <Play aria-hidden="true" size={16} />
                {queryState === "running" ? "Running" : "Run"}
              </button>
              <span className="panel-note">
                Example: select id, venue, status, candidate_count from market_data_pulls limit 25
              </span>
            </div>
          </form>
        </Panel>
      </div>

      <Panel
        eyebrow="Results"
        title={state.result.dataset.label}
        status={`${state.result.rowCount} rows`}
        statusTone="ok"
        className="data-results-panel"
      >
        <div className="data-results-toolbar">
          <label>
            Dataset
            <select
              value={selectedDataset}
              disabled={queryState === "running"}
              onChange={(event) => void selectDataset(event.target.value)}
            >
              {state.metadata.datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.label} ({dataset.rowCount} rows)
                </option>
              ))}
            </select>
          </label>
          <div className="result-summary">
            <Rows3 aria-hidden="true" size={18} />
            <span>{state.result.message}</span>
            <small>{state.result.dataset.table}</small>
          </div>
        </div>
        <DashboardDataGrid
          rows={state.result.rows}
          columns={resultColumns}
          emptyTitle="No rows"
          emptyBody={state.result.message || "The query returned no records."}
          getRowId={(row) => String(row.id ?? JSON.stringify(row))}
          pageSize={25}
          searchPlaceholder="Filter query results"
        />
      </Panel>
    </div>
  );
}

async function runQuery(query: string) {
  return dashboardApi<DataQueryResult>("data/query", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

function displayCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    const text = JSON.stringify(value);
    return text.length > 500 ? `${text.slice(0, 500)}...` : text;
  }
  return String(value);
}
