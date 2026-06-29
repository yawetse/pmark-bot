"use client";

import { Database, Play, Rows3 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { EmptyState, Message, Panel } from "@/components/dashboard/dashboard-primitives";
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

type LoadState =
  | { status: "loading" }
  | { status: "ready"; metadata: DataExplorerMetadata; result: DataQueryResult }
  | { status: "error"; message: string };

const DEFAULT_QUERY = "select * from market_data_pulls limit 25";

export function DataExplorerView() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [selectedDataset, setSelectedDataset] = useState("market_data_pulls");
  const [queryState, setQueryState] = useState<"idle" | "running">("idle");

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
    setQueryState("running");
    const result = await runQuery(query);
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

  function selectDataset(dataset: DataExplorerDataset) {
    setSelectedDataset(dataset.id);
    setQuery(`select * from ${dataset.id} limit 25`);
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

        <Panel eyebrow="Datasets" title="Available tables" className="data-dataset-panel">
          <div className="dataset-list">
            {state.metadata.datasets.map((dataset) => (
              <button
                className="dataset-button"
                data-active={dataset.id === selectedDataset ? "true" : undefined}
                key={dataset.id}
                type="button"
                onClick={() => selectDataset(dataset)}
              >
                <Database aria-hidden="true" size={16} />
                <span>
                  <strong>{dataset.label}</strong>
                  <small>{dataset.rowCount} rows</small>
                </span>
              </button>
            ))}
          </div>
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
        <div className="result-summary">
          <Rows3 aria-hidden="true" size={18} />
          <span>{state.result.message}</span>
          <small>{state.result.dataset.table}</small>
        </div>
        {state.result.rows.length ? (
          <DashboardDataGrid
            rows={state.result.rows}
            columns={resultColumns}
            emptyTitle="No rows"
            emptyBody="The query returned no records."
            getRowId={(row) => String(row.id ?? JSON.stringify(row))}
            pageSize={25}
            searchPlaceholder="Filter query results"
          />
        ) : (
          <EmptyState title="No rows" body={state.result.message || "The query returned no records."} />
        )}
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
