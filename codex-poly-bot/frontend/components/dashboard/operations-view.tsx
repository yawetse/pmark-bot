"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  EconomicsPanel,
  type EconomicsSummaryView,
} from "@/components/dashboard/economics-panel";
import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import {
  ManualRunControl,
  type ManualRunResult,
  type PipelineRunView,
  type PipelineStepView,
} from "@/components/dashboard/manual-run-control";
import {
  MarketDataPanel,
  type MarketDataPullView,
} from "@/components/dashboard/market-data-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const ORDER_STATES = ["refused", "submitted", "filled", "canceled", "failed", "unknown"] as const;
const PIPELINE_STEP_LABELS = ["Data Fetch", "Scanner", "Reasoning / Brain", "Execution", "Exit"] as const;

type OrderState = (typeof ORDER_STATES)[number];

export type OrderEventView = {
  id: string;
  state: OrderState;
  venue: string;
  provider: string;
  createdAt?: string | null;
  message?: string | null;
};

export type HistoricalImportCheckpointView = {
  id: string;
  source: string;
  cursorType: string;
  cursorValue: string;
  status: string;
  lastSuccessAt?: string | null;
  updatedAt?: string | null;
};

export type HistoricalImportView = {
  status: string;
  message: string;
  counts: {
    gammaMarkets: number;
    chainFills: number;
    trades: number;
    walletPositions: number;
    walletStats: number;
    targetWalletSnapshots: number;
    checkpoints: number;
  };
  checkpoints: HistoricalImportCheckpointView[];
  lastUpdatedAt?: string | null;
};

export type BrokerHistoryView = {
  status: string;
  message: string;
  counts: {
    orders: number;
    fills: number;
    positions: number;
    accountSnapshots: number;
    bars: number;
    pnlSnapshots: number;
    checkpoints: number;
  };
  checkpoints: HistoricalImportCheckpointView[];
  lastUpdatedAt?: string | null;
};

export type ScannerCandidateView = {
  id: string;
  scannerRunId?: string | null;
  venue: string;
  instrumentId: string;
  displayName: string;
  symbol?: string | null;
  marketId?: string | null;
  outcomeId?: string | null;
  status: string;
  refusalReason?: string | null;
  strategyNames?: string[];
  price?: string | null;
  liquidity?: string | null;
  spread?: string | null;
  hoursToResolution?: string | null;
  metrics?: Record<string, unknown>;
  createdAt?: string | null;
};

export type ScannerRunView = {
  id?: string | null;
  environment?: string;
  pipelineRunId?: string | null;
  trigger?: string;
  status: string;
  acceptedCount: number;
  rejectedCount: number;
  candidateCount: number;
  sourcePullIds?: string[];
  startedAt?: string | null;
  completedAt?: string | null;
  candidates: ScannerCandidateView[];
};

export type ScannerSummaryView = {
  status: string;
  message: string;
  latestRun?: ScannerRunView | null;
  candidateCount: number;
  acceptedCount: number;
  rejectedCount: number;
  candidates: ScannerCandidateView[];
};

export type ReasoningOutputView = {
  id: string;
  reasoningRunId?: string | null;
  scannerCandidateId?: string | null;
  venue: string;
  instrumentId: string;
  modelProvider: string;
  promptVersion: string;
  status: string;
  refusalReason?: string | null;
  directionalSignal: string;
  signalStrength?: string | null;
  confidence?: string | null;
  estimatedProbability?: string | null;
  costUsd?: string | null;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  checks?: Array<Record<string, unknown>>;
  thesis?: string | null;
  createdAt?: string | null;
};

export type ReasoningRunView = {
  id?: string | null;
  environment?: string;
  pipelineRunId?: string | null;
  scannerRunId?: string | null;
  trigger?: string;
  status: string;
  providerCount: number;
  promptCount: number;
  scoredCount: number;
  skippedCount: number;
  failedCount: number;
  startedAt?: string | null;
  completedAt?: string | null;
  outputs: ReasoningOutputView[];
};

export type ReasoningSummaryView = {
  status: string;
  message: string;
  latestRun?: ReasoningRunView | null;
  promptCount: number;
  scoredCount: number;
  skippedCount: number;
  failedCount: number;
  outputs: ReasoningOutputView[];
};

export type StrategyVoteView = {
  id: string;
  consensusRunId?: string | null;
  reasoningOutputId?: string | null;
  scannerCandidateId?: string | null;
  venue: string;
  instrumentId: string;
  modelProvider: string;
  strategyName: string;
  direction?: string | null;
  confidence?: string | null;
  status: string;
  refusalReason?: string | null;
  inputsHash?: string | null;
  createdAt?: string | null;
};

export type StrategyConsensusOutputView = {
  id: string;
  consensusRunId?: string | null;
  venue: string;
  instrumentId: string;
  modelProvider: string;
  status: string;
  side?: string | null;
  sizeMultiplier?: string | null;
  signalCount: number;
  strategyNames?: string[];
  refusalReason?: string | null;
  createdAt?: string | null;
};

export type StrategyConsensusRunView = {
  id?: string | null;
  environment?: string;
  pipelineRunId?: string | null;
  reasoningRunId?: string | null;
  trigger?: string;
  status: string;
  voteCount: number;
  approvedCount: number;
  refusedCount: number;
  startedAt?: string | null;
  completedAt?: string | null;
  votes: StrategyVoteView[];
  outputs: StrategyConsensusOutputView[];
};

export type StrategyConsensusSummaryView = {
  status: string;
  message: string;
  latestRun?: StrategyConsensusRunView | null;
  voteCount: number;
  approvedCount: number;
  refusedCount: number;
  votes: StrategyVoteView[];
  outputs: StrategyConsensusOutputView[];
};

export type OperationsSummaryView = {
  killSwitch: string;
  openOrders: number;
  cancelProgress: string;
  manualReview: string;
  degradedVenueStatus: string;
  manualReviewState: string;
  orderEvents: OrderEventView[];
  pipelineRuns: PipelineRunView[];
  scanner?: ScannerSummaryView;
  reasoning?: ReasoningSummaryView;
  strategyConsensus?: StrategyConsensusSummaryView;
  historicalImport?: HistoricalImportView;
  brokerHistory?: BrokerHistoryView;
};

const FALLBACK_HISTORICAL_IMPORT: HistoricalImportView = {
  status: "idle",
  message: "No historical Polymarket import records have been stored yet.",
  counts: {
    gammaMarkets: 0,
    chainFills: 0,
    trades: 0,
    walletPositions: 0,
    walletStats: 0,
    targetWalletSnapshots: 0,
    checkpoints: 0,
  },
  checkpoints: [],
  lastUpdatedAt: null,
};

const FALLBACK_BROKER_HISTORY: BrokerHistoryView = {
  status: "idle",
  message: "No Alpaca broker history import records have been stored yet.",
  counts: {
    orders: 0,
    fills: 0,
    positions: 0,
    accountSnapshots: 0,
    bars: 0,
    pnlSnapshots: 0,
    checkpoints: 0,
  },
  checkpoints: [],
  lastUpdatedAt: null,
};

const FALLBACK_SCANNER: ScannerSummaryView = {
  status: "idle",
  message: "No scanner run has been recorded yet.",
  latestRun: null,
  candidateCount: 0,
  acceptedCount: 0,
  rejectedCount: 0,
  candidates: [],
};

const FALLBACK_REASONING: ReasoningSummaryView = {
  status: "idle",
  message: "No reasoning run has been recorded yet.",
  latestRun: null,
  promptCount: 0,
  scoredCount: 0,
  skippedCount: 0,
  failedCount: 0,
  outputs: [],
};

const FALLBACK_STRATEGY_CONSENSUS: StrategyConsensusSummaryView = {
  status: "idle",
  message: "No strategy consensus run has been recorded yet.",
  latestRun: null,
  voteCount: 0,
  approvedCount: 0,
  refusedCount: 0,
  votes: [],
  outputs: [],
};

const FALLBACK_OPERATIONS: OperationsSummaryView = {
  killSwitch: "unknown",
  openOrders: 0,
  cancelProgress: "0 / 0",
  manualReview: "none",
  degradedVenueStatus: "unavailable",
  manualReviewState: "unknown",
  orderEvents: [],
  pipelineRuns: [],
  scanner: FALLBACK_SCANNER,
  reasoning: FALLBACK_REASONING,
  strategyConsensus: FALLBACK_STRATEGY_CONSENSUS,
  historicalImport: FALLBACK_HISTORICAL_IMPORT,
  brokerHistory: FALLBACK_BROKER_HISTORY,
};

export function OperationsView({
  summary = FALLBACK_OPERATIONS,
  marketData,
  economics,
  loadError,
  timeZone = "system",
}: {
  summary?: OperationsSummaryView;
  marketData?: MarketDataPullView;
  economics?: EconomicsSummaryView;
  loadError?: string;
  timeZone?: string;
}) {
  const [latestMarketData, setLatestMarketData] = useState(marketData);
  const [pipelineRuns, setPipelineRuns] = useState(summary.pipelineRuns ?? []);
  const [scanner, setScanner] = useState(summary.scanner ?? FALLBACK_SCANNER);
  const [reasoning, setReasoning] = useState(summary.reasoning ?? FALLBACK_REASONING);
  const [strategyConsensus, setStrategyConsensus] = useState(
    summary.strategyConsensus ?? FALLBACK_STRATEGY_CONSENSUS,
  );
  const displayTimeZone = useResolvedTimeZone(timeZone);
  const pendingEvents = summary.orderEvents.filter(
    (event) => !["filled", "canceled", "failed", "refused"].includes(event.state),
  );
  const terminalEvents = summary.orderEvents.filter((event) =>
    ["filled", "canceled", "failed", "refused"].includes(event.state),
  );

  return (
    <div className="page-stack">
      <section className="panel wide-panel">
        <div className="panel-heading">
          <div>
            <p className="section-label">Operations</p>
            <h1>Trading Activity</h1>
          </div>
          {loadError ? (
            <span className="status blocked">api unavailable</span>
          ) : (
            <span className={`status ${summary.killSwitch === "active" ? "blocked" : "ok"}`}>
              kill switch {summary.killSwitch}
            </span>
          )}
        </div>
        {loadError ? <p className="status-message">{loadError}</p> : null}
        <div className="metric-grid">
          <Metric label="Open orders" value={String(summary.openOrders)} />
          <Metric label="Pending events" value={String(pendingEvents.length)} />
          <Metric label="Cancel progress" value={summary.cancelProgress} />
          <Metric label="Manual review" value={summary.manualReview} />
        </div>
        <ul className="status-list">
          <li>
            <span>Degraded venue status</span>
            <span className={`status ${summary.degradedVenueStatus === "none" ? "ok" : "blocked"}`}>
              {summary.degradedVenueStatus}
            </span>
          </li>
          <li>
            <span>Manual-review state</span>
            <span className={`status ${summary.manualReviewState === "clear" ? "ok" : "blocked"}`}>
              {summary.manualReviewState}
            </span>
          </li>
        </ul>
      </section>

      <ManualRunControl environment={process.env.NEXT_PUBLIC_APP_ENV ?? "local"} onAccepted={onManualRunAccepted} />

      <PipelineRunsPanel runs={pipelineRuns} timeZone={displayTimeZone} />

      <ScannerPanel scanner={scanner} timeZone={displayTimeZone} />

      <ReasoningPanel reasoning={reasoning} timeZone={displayTimeZone} />

      <StrategyConsensusPanel strategyConsensus={strategyConsensus} timeZone={displayTimeZone} />

      <HistoricalImportPanel
        historicalImport={summary.historicalImport ?? FALLBACK_HISTORICAL_IMPORT}
        timeZone={displayTimeZone}
      />

      <BrokerHistoryPanel
        brokerHistory={summary.brokerHistory ?? FALLBACK_BROKER_HISTORY}
        timeZone={displayTimeZone}
      />

      {latestMarketData ? <MarketDataPanel marketData={latestMarketData} timeZone={displayTimeZone} /> : null}

      {economics ? <EconomicsPanel economics={economics} /> : null}

      <section className="panel wide-panel">
        <h2>Pending Orders</h2>
        <OrderTable
          emptyTitle="No pending orders"
          emptyBody="No orders are waiting for fill, cancellation, reconciliation, or manual review."
          events={pendingEvents}
        />
      </section>

      <section className="panel wide-panel">
        <h2>Trade and Order History</h2>
        <OrderTable
          emptyTitle="No trade or order history"
          emptyBody="No simulated or live order events have been recorded yet."
          events={terminalEvents}
        />
      </section>

      <section className="panel wide-panel">
        <KillSwitchControl active={summary.killSwitch === "active"} />
      </section>
    </div>
  );

  function onManualRunAccepted(result: ManualRunResult) {
    setLatestMarketData(result.marketDataPull);
    if (result.pipelineRun) {
      setPipelineRuns((currentRuns) => [
        result.pipelineRun as PipelineRunView,
        ...currentRuns.filter((run) => run.id !== result.pipelineRun?.id),
      ]);
    }
    if (result.scannerRun) {
      const scannerRun = result.scannerRun as ScannerRunView;
      setScanner({
        status: scannerRun.status ?? "idle",
        message: `Latest scanner run accepted ${scannerRun.acceptedCount ?? 0} and rejected ${scannerRun.rejectedCount ?? 0} candidates.`,
        latestRun: scannerRun,
        candidateCount: scannerRun.candidateCount ?? 0,
        acceptedCount: scannerRun.acceptedCount ?? 0,
        rejectedCount: scannerRun.rejectedCount ?? 0,
        candidates: scannerRun.candidates ?? [],
      });
    }
    if (result.reasoningRun) {
      const reasoningRun = result.reasoningRun as ReasoningRunView;
      setReasoning({
        status: reasoningRun.status ?? "idle",
        message: `Latest reasoning run scored ${reasoningRun.scoredCount ?? 0}, skipped ${reasoningRun.skippedCount ?? 0}, and failed ${reasoningRun.failedCount ?? 0} prompts.`,
        latestRun: reasoningRun,
        promptCount: reasoningRun.promptCount ?? 0,
        scoredCount: reasoningRun.scoredCount ?? 0,
        skippedCount: reasoningRun.skippedCount ?? 0,
        failedCount: reasoningRun.failedCount ?? 0,
        outputs: reasoningRun.outputs ?? [],
      });
    }
    if (result.strategyRun) {
      const strategyRun = result.strategyRun as StrategyConsensusRunView;
      setStrategyConsensus({
        status: strategyRun.status ?? "idle",
        message: `Latest strategy consensus recorded ${strategyRun.voteCount ?? 0} votes, approved ${strategyRun.approvedCount ?? 0}, and refused ${strategyRun.refusedCount ?? 0}.`,
        latestRun: strategyRun,
        voteCount: strategyRun.voteCount ?? 0,
        approvedCount: strategyRun.approvedCount ?? 0,
        refusedCount: strategyRun.refusedCount ?? 0,
        votes: strategyRun.votes ?? [],
        outputs: strategyRun.outputs ?? [],
      });
    }
  }
}

function useResolvedTimeZone(preference: string): string {
  const [systemTimeZone, setSystemTimeZone] = useState("UTC");

  useEffect(() => {
    const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (resolved) {
      setSystemTimeZone(resolved);
    }
  }, []);

  return preference === "system" ? systemTimeZone : preference;
}

function OrderTable({
  events,
  emptyTitle,
  emptyBody,
}: {
  events: OrderEventView[];
  emptyTitle: string;
  emptyBody: string;
}) {
  const columns: DashboardGridColumn<OrderEventView>[] = [
    { field: "id", headerName: "Order", minWidth: 180 },
    { field: "state", headerName: "State", minWidth: 130 },
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "provider", headerName: "Provider", minWidth: 130 },
    { field: "message", headerName: "Message", minWidth: 240 },
    { field: "createdAt", headerName: "Created", minWidth: 190 },
  ];

  return (
    <DashboardDataGrid
      rows={events}
      columns={columns}
      emptyTitle={emptyTitle}
      emptyBody={emptyBody}
      getRowId={(event) => event.id}
      searchPlaceholder="Filter orders"
    />
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PipelineRunsPanel({
  runs,
  timeZone,
}: {
  runs: PipelineRunView[];
  timeZone: string;
}) {
  const latestRun = runs[0];
  const latestSteps: PipelineStepView[] = latestRun?.steps.length
    ? latestRun.steps
    : PIPELINE_STEP_LABELS.map((label, index) => ({
        id: `pending-${index + 1}`,
        key: label.toLowerCase().replaceAll(" ", "_").replaceAll("/", "_"),
        order: index + 1,
        label,
        status: "waiting",
        startedAt: null,
        completedAt: null,
        message: "Waiting for the next recorded run.",
        recordIds: [],
      }));
  const columns: DashboardGridColumn<PipelineRunView>[] = [
    { field: "id", headerName: "Run", minWidth: 220 },
    { field: "trigger", headerName: "Trigger", minWidth: 130 },
    { field: "status", headerName: "Status", minWidth: 130 },
    {
      field: "startedAt",
      headerName: "Started",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "completedAt",
      headerName: "Completed",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "metadata",
      headerName: "Candidates",
      minWidth: 130,
      valueGetter: (params) => String(params.data?.metadata?.candidateCount ?? 0),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="pipeline-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Run pipeline</p>
          <h2 id="pipeline-title">Latest run steps</h2>
        </div>
        <span className={`status ${latestRun ? statusClass(latestRun.status) : "idle"}`}>
          {latestRun?.status ?? "idle"}
        </span>
      </div>
      {latestRun ? (
        <div className="pipeline-stepper">
          {latestSteps.map((step) => (
            <article className="pipeline-step" key={step.id}>
              <span className="pipeline-step-index">{step.order}</span>
              <div>
                <div className="pipeline-step-heading">
                  <strong>{step.label}</strong>
                  <span className={`status ${statusClass(step.status)}`}>{step.status}</span>
                </div>
                <p>{step.message}</p>
                <div className="pipeline-step-meta">
                  <span>Records: {step.recordIds?.length ?? 0}</span>
                  <span>Completed: {formatDateTime(step.completedAt, timeZone)}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="panel-note">No manual or scheduled runs have been recorded yet.</p>
      )}
      <DashboardDataGrid
        rows={runs}
        columns={columns}
        emptyTitle="No runs recorded"
        emptyBody="Manual and scheduled runs will appear here after they start."
        getRowId={(run) => run.id}
        searchPlaceholder="Filter runs"
      />
    </section>
  );
}

function HistoricalImportPanel({
  historicalImport,
  timeZone,
}: {
  historicalImport: HistoricalImportView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<HistoricalImportCheckpointView>[] = [
    { field: "source", headerName: "Source", minWidth: 220 },
    { field: "status", headerName: "Status", minWidth: 130 },
    { field: "cursorType", headerName: "Cursor", minWidth: 130 },
    { field: "cursorValue", headerName: "Value", minWidth: 140 },
    {
      field: "lastSuccessAt",
      headerName: "Last success",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "updatedAt",
      headerName: "Updated",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="historical-import-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Historical import</p>
          <h2 id="historical-import-title">Polymarket history</h2>
        </div>
        <span className={`status ${statusClass(historicalImport.status)}`}>
          {historicalImport.status}
        </span>
      </div>
      <p className="panel-note">{historicalImport.message}</p>
      <div className="metric-grid">
        <Metric label="Gamma markets" value={String(historicalImport.counts.gammaMarkets)} />
        <Metric label="Chain fills" value={String(historicalImport.counts.chainFills)} />
        <Metric label="Trades" value={String(historicalImport.counts.trades)} />
        <Metric label="Wallet stats" value={String(historicalImport.counts.walletStats)} />
      </div>
      <div className="metric-grid">
        <Metric label="Wallet positions" value={String(historicalImport.counts.walletPositions)} />
        <Metric
          label="Target snapshots"
          value={String(historicalImport.counts.targetWalletSnapshots)}
        />
        <Metric label="Checkpoints" value={String(historicalImport.counts.checkpoints)} />
        <Metric label="Updated" value={formatDateTime(historicalImport.lastUpdatedAt, timeZone)} />
      </div>
      <DashboardDataGrid
        rows={historicalImport.checkpoints}
        columns={columns}
        emptyTitle="No import checkpoints"
        emptyBody="Historical import checkpoints will appear after Gamma or Polygon backfills run."
        getRowId={(checkpoint) => checkpoint.id}
        searchPlaceholder="Filter checkpoints"
      />
    </section>
  );
}

function ScannerPanel({
  scanner,
  timeZone,
}: {
  scanner: ScannerSummaryView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<ScannerCandidateView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "displayName", headerName: "Candidate", minWidth: 260 },
    { field: "status", headerName: "State", minWidth: 130 },
    { field: "refusalReason", headerName: "Refusal", minWidth: 220 },
    {
      field: "strategyNames",
      headerName: "Strategies",
      minWidth: 220,
      valueGetter: (params) => (params.data?.strategyNames ?? []).join(", "),
    },
    { field: "price", headerName: "Price", minWidth: 110 },
    { field: "liquidity", headerName: "Liquidity", minWidth: 130 },
    { field: "spread", headerName: "Spread", minWidth: 110 },
    { field: "hoursToResolution", headerName: "Hours", minWidth: 110 },
    {
      field: "metrics",
      headerName: "Signal details",
      minWidth: 260,
      valueGetter: (params) => scannerMetricSummary(params.data?.metrics),
    },
    {
      field: "createdAt",
      headerName: "Scanned",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="scanner-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Scanner</p>
          <h2 id="scanner-title">Candidate filters</h2>
        </div>
        <span className={`status ${statusClass(scanner.status)}`}>{scanner.status}</span>
      </div>
      <p className="panel-note">{scanner.message}</p>
      <div className="metric-grid">
        <Metric label="Candidates" value={String(scanner.candidateCount)} />
        <Metric label="Accepted" value={String(scanner.acceptedCount)} />
        <Metric label="Rejected" value={String(scanner.rejectedCount)} />
        <Metric
          label="Completed"
          value={formatDateTime(scanner.latestRun?.completedAt, timeZone)}
        />
      </div>
      <DashboardDataGrid
        rows={scanner.candidates}
        columns={columns}
        emptyTitle="No scanner candidates"
        emptyBody="Scanner output will appear after a manual or scheduled run evaluates provider candidates."
        getRowId={(candidate) => candidate.id}
        searchPlaceholder="Filter scanner candidates"
      />
    </section>
  );
}

function ReasoningPanel({
  reasoning,
  timeZone,
}: {
  reasoning: ReasoningSummaryView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<ReasoningOutputView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "instrumentId", headerName: "Instrument", minWidth: 220 },
    { field: "modelProvider", headerName: "Provider", minWidth: 130 },
    { field: "promptVersion", headerName: "Prompt", minWidth: 150 },
    { field: "status", headerName: "State", minWidth: 120 },
    { field: "refusalReason", headerName: "Refusal", minWidth: 220 },
    { field: "directionalSignal", headerName: "Signal", minWidth: 140 },
    { field: "signalStrength", headerName: "Strength", minWidth: 120 },
    { field: "confidence", headerName: "Confidence", minWidth: 130 },
    { field: "estimatedProbability", headerName: "Probability", minWidth: 130 },
    { field: "costUsd", headerName: "Cost", minWidth: 110 },
    { field: "totalTokens", headerName: "Tokens", minWidth: 110 },
    {
      field: "checks",
      headerName: "Checks",
      minWidth: 280,
      valueGetter: (params) => reasoningCheckSummary(params.data?.checks),
    },
    { field: "thesis", headerName: "Thesis", minWidth: 320 },
    {
      field: "createdAt",
      headerName: "Scored",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="reasoning-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Reasoning / Brain</p>
          <h2 id="reasoning-title">LLM scoring output</h2>
        </div>
        <span className={`status ${statusClass(reasoning.status)}`}>{reasoning.status}</span>
      </div>
      <p className="panel-note">{reasoning.message}</p>
      <div className="metric-grid">
        <Metric label="Prompts" value={String(reasoning.promptCount)} />
        <Metric label="Scored" value={String(reasoning.scoredCount)} />
        <Metric label="Skipped" value={String(reasoning.skippedCount)} />
        <Metric label="Failed" value={String(reasoning.failedCount)} />
      </div>
      <DashboardDataGrid
        rows={reasoning.outputs}
        columns={columns}
        emptyTitle="No reasoning output"
        emptyBody="Reasoning rows will appear after accepted scanner candidates are sent to configured model providers."
        getRowId={(output) => output.id}
        searchPlaceholder="Filter reasoning output"
      />
    </section>
  );
}

function StrategyConsensusPanel({
  strategyConsensus,
  timeZone,
}: {
  strategyConsensus: StrategyConsensusSummaryView;
  timeZone: string;
}) {
  const voteColumns: DashboardGridColumn<StrategyVoteView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "instrumentId", headerName: "Instrument", minWidth: 220 },
    { field: "modelProvider", headerName: "Provider", minWidth: 130 },
    { field: "strategyName", headerName: "Strategy", minWidth: 160 },
    { field: "status", headerName: "State", minWidth: 120 },
    { field: "direction", headerName: "Direction", minWidth: 120 },
    { field: "confidence", headerName: "Confidence", minWidth: 130 },
    { field: "refusalReason", headerName: "Refusal", minWidth: 240 },
    {
      field: "createdAt",
      headerName: "Voted",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];
  const outputColumns: DashboardGridColumn<StrategyConsensusOutputView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "instrumentId", headerName: "Instrument", minWidth: 220 },
    { field: "modelProvider", headerName: "Provider", minWidth: 130 },
    { field: "status", headerName: "State", minWidth: 120 },
    { field: "side", headerName: "Side", minWidth: 100 },
    { field: "sizeMultiplier", headerName: "Size", minWidth: 110 },
    { field: "signalCount", headerName: "Signals", minWidth: 110 },
    {
      field: "strategyNames",
      headerName: "Strategies",
      minWidth: 220,
      valueGetter: (params) => (params.data?.strategyNames ?? []).join(", "),
    },
    { field: "refusalReason", headerName: "Refusal", minWidth: 240 },
    {
      field: "createdAt",
      headerName: "Resolved",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="strategy-consensus-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Strategy consensus</p>
          <h2 id="strategy-consensus-title">Votes before risk sizing</h2>
        </div>
        <span className={`status ${statusClass(strategyConsensus.status)}`}>
          {strategyConsensus.status}
        </span>
      </div>
      <p className="panel-note">{strategyConsensus.message}</p>
      <div className="metric-grid">
        <Metric label="Votes" value={String(strategyConsensus.voteCount)} />
        <Metric label="Approved" value={String(strategyConsensus.approvedCount)} />
        <Metric label="Refused" value={String(strategyConsensus.refusedCount)} />
        <Metric
          label="Completed"
          value={formatDateTime(strategyConsensus.latestRun?.completedAt, timeZone)}
        />
      </div>
      <DashboardDataGrid
        rows={strategyConsensus.votes}
        columns={voteColumns}
        emptyTitle="No strategy votes"
        emptyBody="Strategy votes will appear after scored reasoning output is evaluated by the consensus step."
        getRowId={(vote) => vote.id}
        searchPlaceholder="Filter strategy votes"
      />
      <DashboardDataGrid
        rows={strategyConsensus.outputs}
        columns={outputColumns}
        emptyTitle="No consensus outputs"
        emptyBody="Consensus outputs will appear after strategy votes are resolved for each scored candidate."
        getRowId={(output) => output.id}
        searchPlaceholder="Filter consensus outputs"
      />
    </section>
  );
}

function BrokerHistoryPanel({
  brokerHistory,
  timeZone,
}: {
  brokerHistory: BrokerHistoryView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<HistoricalImportCheckpointView>[] = [
    { field: "source", headerName: "Source", minWidth: 220 },
    { field: "status", headerName: "Status", minWidth: 130 },
    { field: "cursorType", headerName: "Cursor", minWidth: 130 },
    { field: "cursorValue", headerName: "Value", minWidth: 140 },
    {
      field: "lastSuccessAt",
      headerName: "Last success",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "updatedAt",
      headerName: "Updated",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="broker-history-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Broker history</p>
          <h2 id="broker-history-title">Alpaca history</h2>
        </div>
        <span className={`status ${statusClass(brokerHistory.status)}`}>
          {brokerHistory.status}
        </span>
      </div>
      <p className="panel-note">{brokerHistory.message}</p>
      <div className="metric-grid">
        <Metric label="Orders" value={String(brokerHistory.counts.orders)} />
        <Metric label="Fills" value={String(brokerHistory.counts.fills)} />
        <Metric label="Positions" value={String(brokerHistory.counts.positions)} />
        <Metric label="Account snapshots" value={String(brokerHistory.counts.accountSnapshots)} />
      </div>
      <div className="metric-grid">
        <Metric label="Stock bars" value={String(brokerHistory.counts.bars)} />
        <Metric label="P&L snapshots" value={String(brokerHistory.counts.pnlSnapshots)} />
        <Metric label="Checkpoints" value={String(brokerHistory.counts.checkpoints)} />
        <Metric label="Updated" value={formatDateTime(brokerHistory.lastUpdatedAt, timeZone)} />
      </div>
      <DashboardDataGrid
        rows={brokerHistory.checkpoints}
        columns={columns}
        emptyTitle="No broker checkpoints"
        emptyBody="Alpaca broker history checkpoints will appear after order, fill, position, or bar imports run."
        getRowId={(checkpoint) => checkpoint.id}
        searchPlaceholder="Filter broker checkpoints"
      />
    </section>
  );
}

function scannerMetricSummary(metrics: Record<string, unknown> | undefined): string {
  if (!metrics) {
    return "";
  }
  const parts = [
    metricPart(metrics, "targetWalletOverlap", "wallets"),
    metricPart(metrics, "momentumPct", "momentum"),
    metricPart(metrics, "gapPct", "gap"),
    metricPart(metrics, "unusualVolumeRatio", "volume"),
    metricPart(metrics, "hoursToResolution", "hours"),
  ].filter(Boolean);
  return parts.join("; ");
}

function reasoningCheckSummary(checks: Array<Record<string, unknown>> | undefined): string {
  if (!checks?.length) {
    return "";
  }
  return checks
    .map((check) => {
      const name = check.name ? String(check.name) : "check";
      const status = check.status ? String(check.status) : "unknown";
      return `${name}: ${status}`;
    })
    .join("; ");
}

function metricPart(metrics: Record<string, unknown>, key: string, label: string): string {
  const value = metrics[key];
  if (value === null || value === undefined || value === "") {
    return "";
  }
  return `${label}: ${String(value)}`;
}

function formatDateTime(value: string | null | undefined, timeZone: string): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "not recorded";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(date);
}

function statusClass(status: string): "ok" | "idle" | "blocked" {
  if (["blocked", "failed", "rate_limited", "skipped"].includes(status)) {
    return "blocked";
  }
  if (
    ["waiting", "idle", "empty", "no_candidates_passed", "no_candidates", "no_scores", "no_votes"].includes(
      status,
    )
  ) {
    return "idle";
  }
  return "ok";
}

function KillSwitchControl({ active }: { active: boolean }) {
  const [reason, setReason] = useState("operator stop");
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<
    | { status: "idle" }
    | { status: "submitting" }
    | { status: "done"; message: string }
    | { status: "error"; message: string }
  >({ status: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed || active) {
      return;
    }
    setState({ status: "submitting" });
    const result = await dashboardApi<{ active?: boolean; live_disabled?: boolean }>("kill-switch", {
      method: "POST",
      body: JSON.stringify({
        environment: process.env.NEXT_PUBLIC_APP_ENV ?? "local",
        reason,
      }),
    });
    if (!result.ok) {
      setState({ status: "error", message: result.message });
      return;
    }
    setState({
      status: "done",
      message: result.data.live_disabled
        ? "Kill switch active. Live trading is disabled."
        : "Kill switch request accepted.",
    });
  }

  return (
    <form className="danger-zone" onSubmit={onSubmit}>
      <div>
        <p className="section-label">Emergency control</p>
        <h2>Kill Switch</h2>
        <p>
          Stops new live orders and asks the backend to cancel known open live orders.
          Dry-run records can still be reviewed.
        </p>
      </div>
      <label>
        Reason
        <input value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <label className="checkbox-row">
        <input
          checked={confirmed}
          disabled={active}
          type="checkbox"
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>I understand this disables live trading.</span>
      </label>
      <button className="button danger" disabled={!confirmed || active || state.status === "submitting"} type="submit">
        {active ? "Kill switch active" : "Activate kill switch"}
      </button>
      {state.status === "done" || state.status === "error" ? (
        <p className="status-message">{state.message}</p>
      ) : null}
    </form>
  );
}
