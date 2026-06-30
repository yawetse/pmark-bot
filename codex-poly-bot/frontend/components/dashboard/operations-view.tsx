"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  EconomicsPanel,
  type EconomicsSummaryView,
} from "@/components/dashboard/economics-panel";
import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { Disclosure } from "@/components/dashboard/dashboard-primitives";
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
import {
  FALLBACK_TICK_SUMMARY,
  TickSummaryPanel,
  type TickSummaryView,
} from "@/components/dashboard/tick-summary-panel";
import { dashboardApi } from "@/lib/api";
import { useDashboardRealtime } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const ORDER_STATES = ["refused", "submitted", "filled", "canceled", "failed", "unknown"] as const;
const PIPELINE_STEP_LABELS = ["Data Fetch", "Scanner", "Reasoning / Brain", "Execution", "Exit"] as const;
const DAILY_TICK_SUMMARY_WINDOW_MINUTES = 24 * 60;

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

export type OrderIntentView = {
  id: string;
  executionRunId?: string | null;
  pipelineRunId?: string | null;
  consensusOutputId?: string | null;
  venue: string;
  instrumentId: string;
  modelProvider: string;
  side: string;
  orderType: string;
  status: string;
  notionalUsd?: string | null;
  sizeMultiplier?: string | null;
  idempotencyKey?: string | null;
  refusalReason?: string | null;
  venueOrderId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type ExecutionRunView = {
  id?: string | null;
  environment?: string;
  pipelineRunId?: string | null;
  strategyConsensusRunId?: string | null;
  trigger?: string;
  status: string;
  intentCount: number;
  submittedCount: number;
  simulatedCount: number;
  refusedCount: number;
  reconciliationCount?: number;
  startedAt?: string | null;
  completedAt?: string | null;
  intents: OrderIntentView[];
};

export type ExecutionSummaryView = {
  status: string;
  message: string;
  latestRun?: ExecutionRunView | null;
  intentCount: number;
  submittedCount: number;
  simulatedCount: number;
  refusedCount: number;
  intents: OrderIntentView[];
};

export type ExitIntentView = {
  id: string;
  exitRunId?: string | null;
  pipelineRunId?: string | null;
  venue: string;
  instrumentId: string;
  positionId: string;
  modelProvider?: string | null;
  triggerType: string;
  status: string;
  side: string;
  quantity?: string | null;
  notionalUsd?: string | null;
  threshold?: string | null;
  observedValue?: string | null;
  idempotencyKey?: string | null;
  refusalReason?: string | null;
  venueOrderId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type ExitRunView = {
  id?: string | null;
  environment?: string;
  pipelineRunId?: string | null;
  trigger?: string;
  status: string;
  openPositionCount: number;
  triggeredCount: number;
  submittedCount: number;
  simulatedCount: number;
  refusedCount: number;
  startedAt?: string | null;
  completedAt?: string | null;
  intents: ExitIntentView[];
};

export type ExitSummaryView = {
  status: string;
  message: string;
  latestRun?: ExitRunView | null;
  openPositionCount: number;
  triggeredCount: number;
  submittedCount: number;
  simulatedCount: number;
  refusedCount: number;
  intents: ExitIntentView[];
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
  tickSummary?: TickSummaryView;
  scanner?: ScannerSummaryView;
  reasoning?: ReasoningSummaryView;
  strategyConsensus?: StrategyConsensusSummaryView;
  execution?: ExecutionSummaryView;
  exit?: ExitSummaryView;
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

const FALLBACK_EXECUTION: ExecutionSummaryView = {
  status: "idle",
  message: "No execution run has been recorded yet.",
  latestRun: null,
  intentCount: 0,
  submittedCount: 0,
  simulatedCount: 0,
  refusedCount: 0,
  intents: [],
};

const FALLBACK_EXIT: ExitSummaryView = {
  status: "idle",
  message: "No exit run has been recorded yet.",
  latestRun: null,
  openPositionCount: 0,
  triggeredCount: 0,
  submittedCount: 0,
  simulatedCount: 0,
  refusedCount: 0,
  intents: [],
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
  tickSummary: FALLBACK_TICK_SUMMARY,
  scanner: FALLBACK_SCANNER,
  reasoning: FALLBACK_REASONING,
  strategyConsensus: FALLBACK_STRATEGY_CONSENSUS,
  execution: FALLBACK_EXECUTION,
  exit: FALLBACK_EXIT,
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
  const [currentSummary, setCurrentSummary] = useState(summary);
  const [latestMarketData, setLatestMarketData] = useState(marketData);
  const [pipelineRuns, setPipelineRuns] = useState(summary.pipelineRuns ?? []);
  const [tickSummary, setTickSummary] = useState(summary.tickSummary ?? FALLBACK_TICK_SUMMARY);
  const [tickSummaryRefreshing, setTickSummaryRefreshing] = useState(false);
  const [scanner, setScanner] = useState(summary.scanner ?? FALLBACK_SCANNER);
  const [reasoning, setReasoning] = useState(summary.reasoning ?? FALLBACK_REASONING);
  const [strategyConsensus, setStrategyConsensus] = useState(
    summary.strategyConsensus ?? FALLBACK_STRATEGY_CONSENSUS,
  );
  const [execution, setExecution] = useState(summary.execution ?? FALLBACK_EXECUTION);
  const [exit, setExit] = useState(summary.exit ?? FALLBACK_EXIT);
  const displayTimeZone = useResolvedTimeZone(timeZone);
  const pendingEvents = currentSummary.orderEvents.filter(
    (event) => !["filled", "canceled", "failed", "refused"].includes(event.state),
  );
  const terminalEvents = currentSummary.orderEvents.filter((event) =>
    ["filled", "canceled", "failed", "refused"].includes(event.state),
  );

  const onRealtimeSnapshot = useCallback((snapshot: { operations: OperationsSummaryView; marketData: MarketDataPullView }) => {
    setCurrentSummary(snapshot.operations);
    setLatestMarketData(snapshot.marketData);
    setPipelineRuns(snapshot.operations.pipelineRuns ?? []);
    setScanner(snapshot.operations.scanner ?? FALLBACK_SCANNER);
    setReasoning(snapshot.operations.reasoning ?? FALLBACK_REASONING);
    setStrategyConsensus(snapshot.operations.strategyConsensus ?? FALLBACK_STRATEGY_CONSENSUS);
    setExecution(snapshot.operations.execution ?? FALLBACK_EXECUTION);
    setExit(snapshot.operations.exit ?? FALLBACK_EXIT);
  }, []);
  const realtime = useDashboardRealtime({ onSnapshot: onRealtimeSnapshot });

  useEffect(() => {
    void refreshTickSummary(false);
  }, []);

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
            <span className={`status ${currentSummary.killSwitch === "active" ? "blocked" : "ok"}`}>
              kill switch {currentSummary.killSwitch}
            </span>
          )}
        </div>
        <p className="panel-note">
          Review the current operating gates first, then move through the run workflow from
          candidate intake to execution, exits, imports, and emergency controls.
        </p>
        {loadError ? <p className="status-message">{loadError}</p> : null}
        <div className="metric-grid">
          <Metric label="Open orders" value={String(currentSummary.openOrders)} />
          <Metric label="Pending events" value={String(pendingEvents.length)} />
          <Metric label="Cancel progress" value={currentSummary.cancelProgress} />
          <Metric label="Manual review" value={currentSummary.manualReview} />
        </div>
        <ul className="status-list">
          <li>
            <span>Degraded venue status</span>
            <span className={`status ${currentSummary.degradedVenueStatus === "none" ? "ok" : "blocked"}`}>
              {currentSummary.degradedVenueStatus}
            </span>
          </li>
          <li>
            <span>Manual-review state</span>
            <span className={`status ${currentSummary.manualReviewState === "clear" ? "ok" : "blocked"}`}>
              {currentSummary.manualReviewState}
            </span>
          </li>
          <li>
            <span>Realtime updates</span>
            <span className={`status ${realtime.status === "connected" ? "ok" : realtime.status === "offline" ? "blocked" : "idle"}`}>
              {realtime.status}
            </span>
          </li>
        </ul>
      </section>

      <section className="panel wide-panel" aria-labelledby="workflow-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">Workflow map</p>
            <h2 id="workflow-title">Operate in sequence</h2>
          </div>
          <span className="status idle">dry-run safe</span>
        </div>
        <div className="operation-workflow-grid">
          <WorkflowLink href="#pipeline-title" label="Run pipeline" value={String(pipelineRuns.length)} detail="Recorded runs" />
          <WorkflowLink href="#scanner-title" label="Scanner" value={String(scanner.candidateCount)} detail="Candidates" />
          <WorkflowLink href="#reasoning-title" label="Reasoning / Brain" value={String(reasoning.scoredCount)} detail="Scored" />
          <WorkflowLink href="#strategy-consensus-title" label="Strategy" value={String(strategyConsensus.approvedCount)} detail="Approved" />
          <WorkflowLink href="#execution-title" label="Execution" value={String(execution.intentCount)} detail="Intents" />
          <WorkflowLink href="#exit-title" label="Exit" value={String(exit.triggeredCount)} detail="Triggered" />
          <WorkflowLink href="#historical-import-title" label="Imports" value={String(currentSummary.historicalImport?.counts.checkpoints ?? 0)} detail="Checkpoints" />
          <WorkflowLink href="#kill-switch-title" label="Kill Switch" value={currentSummary.killSwitch} detail="Emergency control" />
        </div>
      </section>

      <ManualRunControl environment={process.env.NEXT_PUBLIC_APP_ENV ?? "local"} onAccepted={onManualRunAccepted} />

      <TickSummaryPanel
        onRefresh={() => void refreshTickSummary(true)}
        refreshing={tickSummaryRefreshing}
        summary={tickSummary}
        timeZone={displayTimeZone}
      />

      <PipelineRunsPanel runs={pipelineRuns} timeZone={displayTimeZone} />

      <ScannerPanel scanner={scanner} timeZone={displayTimeZone} />

      <ReasoningPanel reasoning={reasoning} timeZone={displayTimeZone} />

      <StrategyConsensusPanel strategyConsensus={strategyConsensus} timeZone={displayTimeZone} />

      <ExecutionPanel execution={execution} timeZone={displayTimeZone} />

      <ExitPanel exit={exit} timeZone={displayTimeZone} />

      <HistoricalImportPanel
        historicalImport={currentSummary.historicalImport ?? FALLBACK_HISTORICAL_IMPORT}
        timeZone={displayTimeZone}
      />

      <BrokerHistoryPanel
        brokerHistory={currentSummary.brokerHistory ?? FALLBACK_BROKER_HISTORY}
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
        <KillSwitchControl active={currentSummary.killSwitch === "active"} />
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
    if (result.executionRun) {
      const executionRun = result.executionRun as ExecutionRunView;
      setExecution({
        status: executionRun.status ?? "idle",
        message: `Latest execution recorded ${executionRun.intentCount ?? 0} intents, simulated ${executionRun.simulatedCount ?? 0}, submitted ${executionRun.submittedCount ?? 0}, and refused ${executionRun.refusedCount ?? 0}.`,
        latestRun: executionRun,
        intentCount: executionRun.intentCount ?? 0,
        submittedCount: executionRun.submittedCount ?? 0,
        simulatedCount: executionRun.simulatedCount ?? 0,
        refusedCount: executionRun.refusedCount ?? 0,
        intents: executionRun.intents ?? [],
      });
    }
    if (result.exitRun) {
      const exitRun = result.exitRun as ExitRunView;
      setExit({
        status: exitRun.status ?? "idle",
        message: `Latest exit run saw ${exitRun.openPositionCount ?? 0} open positions and recorded ${exitRun.triggeredCount ?? 0} exit intents.`,
        latestRun: exitRun,
        openPositionCount: exitRun.openPositionCount ?? 0,
        triggeredCount: exitRun.triggeredCount ?? 0,
        submittedCount: exitRun.submittedCount ?? 0,
        simulatedCount: exitRun.simulatedCount ?? 0,
        refusedCount: exitRun.refusedCount ?? 0,
        intents: exitRun.intents ?? [],
      });
    }
  }

  async function refreshTickSummary(forceRefresh: boolean) {
    setTickSummaryRefreshing(true);
    try {
      const result = forceRefresh
        ? await dashboardApi<TickSummaryView>("operations/tick-summary", {
            method: "POST",
            body: JSON.stringify({ window_minutes: DAILY_TICK_SUMMARY_WINDOW_MINUTES }),
          })
        : await dashboardApi<TickSummaryView>(
            `operations/tick-summary?window_minutes=${DAILY_TICK_SUMMARY_WINDOW_MINUTES}`,
          );
      if (result.ok) {
        setTickSummary(result.data);
      }
    } finally {
      setTickSummaryRefreshing(false);
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
    <Disclosure title={events.length === 1 ? "View 1 order record" : `View ${events.length} order records`}>
      <DashboardDataGrid
        rows={events}
        columns={columns}
        emptyTitle={emptyTitle}
        emptyBody={emptyBody}
        getRowId={(event) => event.id}
        searchPlaceholder="Filter orders"
      />
    </Disclosure>
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

function WorkflowLink({
  href,
  label,
  value,
  detail,
}: {
  href: string;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <a className="workflow-link" href={href}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </a>
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
  const stepColumns: DashboardGridColumn<PipelineStepView>[] = [
    { field: "order", headerName: "Step", minWidth: 90 },
    { field: "label", headerName: "Name", minWidth: 180 },
    { field: "status", headerName: "Status", minWidth: 130 },
    {
      field: "recordIds",
      headerName: "Records",
      minWidth: 140,
      valueGetter: (params) => String(params.data?.recordIds?.length ?? 0),
    },
    {
      field: "metrics",
      headerName: "Metrics",
      minWidth: 260,
      valueGetter: (params) => jsonSummary(params.data?.metrics),
    },
    {
      field: "inputs",
      headerName: "Inputs",
      minWidth: 280,
      valueGetter: (params) => jsonSummary(params.data?.inputs),
    },
    {
      field: "outputs",
      headerName: "Outputs",
      minWidth: 280,
      valueGetter: (params) => jsonSummary(params.data?.outputs),
    },
    {
      field: "decisions",
      headerName: "Decisions",
      minWidth: 320,
      valueGetter: (params) => jsonSummary(params.data?.decisions),
    },
    {
      field: "completedAt",
      headerName: "Completed",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
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
      <p className="section-label">Pipeline detail</p>
      <Disclosure title={`View ${latestSteps.length} step records`}>
        <DashboardDataGrid
          rows={latestSteps}
          columns={stepColumns}
          emptyTitle="No step records"
          emptyBody="Pipeline step records will appear after a run starts."
          getRowId={(step) => step.id}
          pageSize={5}
          searchPlaceholder="Filter run steps"
        />
      </Disclosure>
      <Disclosure title={runs.length === 1 ? "View 1 pipeline run" : `View ${runs.length} pipeline runs`}>
        <DashboardDataGrid
          rows={runs}
          columns={columns}
          emptyTitle="No runs recorded"
          emptyBody="Manual and scheduled runs will appear here after they start."
          getRowId={(run) => run.id}
          searchPlaceholder="Filter runs"
        />
      </Disclosure>
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
      <p className="panel-note">
        Imported history comes from clean-room Gamma metadata and Polygon OrderFilled
        backfills. Scanner, reasoning, execution, and exit records below are created by
        the trading loop.
      </p>
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
      <Disclosure
        title={
          historicalImport.checkpoints.length === 1
            ? "View 1 import checkpoint"
            : `View ${historicalImport.checkpoints.length} import checkpoints`
        }
      >
        <DashboardDataGrid
          rows={historicalImport.checkpoints}
          columns={columns}
          emptyTitle="No import checkpoints"
          emptyBody="Historical import checkpoints will appear after Gamma or Polygon backfills run."
          getRowId={(checkpoint) => checkpoint.id}
          searchPlaceholder="Filter checkpoints"
        />
      </Disclosure>
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
      <p className="panel-note">
        Scanner results come from current provider market data and persisted historical context.
      </p>
      <div className="metric-grid">
        <Metric label="Candidates" value={String(scanner.candidateCount)} />
        <Metric label="Accepted" value={String(scanner.acceptedCount)} />
        <Metric label="Rejected" value={String(scanner.rejectedCount)} />
        <Metric
          label="Completed"
          value={formatDateTime(scanner.latestRun?.completedAt, timeZone)}
        />
      </div>
      <Disclosure
        title={
          scanner.candidates.length === 1
            ? "View 1 scanner candidate"
            : `View ${scanner.candidates.length} scanner candidates`
        }
      >
        <DashboardDataGrid
          rows={scanner.candidates}
          columns={columns}
          emptyTitle="No scanner candidates"
          emptyBody="Scanner output will appear after a manual or scheduled run evaluates provider candidates."
          getRowId={(candidate) => candidate.id}
          searchPlaceholder="Filter scanner candidates"
        />
      </Disclosure>
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
      <Disclosure
        title={
          reasoning.outputs.length === 1
            ? "View 1 reasoning output"
            : `View ${reasoning.outputs.length} reasoning outputs`
        }
      >
        <DashboardDataGrid
          rows={reasoning.outputs}
          columns={columns}
          emptyTitle="No reasoning output"
          emptyBody="Reasoning rows will appear after accepted scanner candidates are sent to configured model providers."
          getRowId={(output) => output.id}
          searchPlaceholder="Filter reasoning output"
        />
      </Disclosure>
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
      <Disclosure
        title={
          strategyConsensus.votes.length === 1
            ? "View 1 strategy vote"
            : `View ${strategyConsensus.votes.length} strategy votes`
        }
      >
        <DashboardDataGrid
          rows={strategyConsensus.votes}
          columns={voteColumns}
          emptyTitle="No strategy votes"
          emptyBody="Strategy votes will appear after scored reasoning output is evaluated by the consensus step."
          getRowId={(vote) => vote.id}
          searchPlaceholder="Filter strategy votes"
        />
      </Disclosure>
      <Disclosure
        title={
          strategyConsensus.outputs.length === 1
            ? "View 1 consensus output"
            : `View ${strategyConsensus.outputs.length} consensus outputs`
        }
      >
        <DashboardDataGrid
          rows={strategyConsensus.outputs}
          columns={outputColumns}
          emptyTitle="No consensus outputs"
          emptyBody="Consensus outputs will appear after strategy votes are resolved for each scored candidate."
          getRowId={(output) => output.id}
          searchPlaceholder="Filter consensus outputs"
        />
      </Disclosure>
    </section>
  );
}

function ExecutionPanel({
  execution,
  timeZone,
}: {
  execution: ExecutionSummaryView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<OrderIntentView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "instrumentId", headerName: "Instrument", minWidth: 220 },
    { field: "modelProvider", headerName: "Provider", minWidth: 130 },
    { field: "status", headerName: "State", minWidth: 120 },
    { field: "side", headerName: "Side", minWidth: 100 },
    { field: "orderType", headerName: "Type", minWidth: 100 },
    { field: "notionalUsd", headerName: "Notional", minWidth: 120 },
    { field: "sizeMultiplier", headerName: "Size", minWidth: 110 },
    { field: "refusalReason", headerName: "Refusal", minWidth: 260 },
    { field: "venueOrderId", headerName: "Venue order", minWidth: 180 },
    {
      field: "createdAt",
      headerName: "Created",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="execution-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Execution</p>
          <h2 id="execution-title">Risk gates and order intents</h2>
        </div>
        <span className={`status ${statusClass(execution.status)}`}>{execution.status}</span>
      </div>
      <p className="panel-note">{execution.message}</p>
      <div className="metric-grid">
        <Metric label="Intents" value={String(execution.intentCount)} />
        <Metric label="Simulated" value={String(execution.simulatedCount)} />
        <Metric label="Submitted" value={String(execution.submittedCount)} />
        <Metric label="Refused" value={String(execution.refusedCount)} />
      </div>
      <Disclosure
        title={
          execution.intents.length === 1
            ? "View 1 order intent"
            : `View ${execution.intents.length} order intents`
        }
      >
        <DashboardDataGrid
          rows={execution.intents}
          columns={columns}
          emptyTitle="No order intents"
          emptyBody="Order intents will appear after approved consensus output passes risk gates."
          getRowId={(intent) => intent.id}
          searchPlaceholder="Filter order intents"
        />
      </Disclosure>
    </section>
  );
}

function ExitPanel({
  exit,
  timeZone,
}: {
  exit: ExitSummaryView;
  timeZone: string;
}) {
  const columns: DashboardGridColumn<ExitIntentView>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "instrumentId", headerName: "Instrument", minWidth: 220 },
    { field: "positionId", headerName: "Position", minWidth: 220 },
    { field: "triggerType", headerName: "Trigger", minWidth: 150 },
    { field: "status", headerName: "State", minWidth: 120 },
    { field: "quantity", headerName: "Qty", minWidth: 100 },
    { field: "notionalUsd", headerName: "Notional", minWidth: 120 },
    { field: "threshold", headerName: "Threshold", minWidth: 120 },
    { field: "observedValue", headerName: "Observed", minWidth: 120 },
    { field: "refusalReason", headerName: "Refusal", minWidth: 260 },
    {
      field: "createdAt",
      headerName: "Created",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="exit-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Exit</p>
          <h2 id="exit-title">Open-position monitoring</h2>
        </div>
        <span className={`status ${statusClass(exit.status)}`}>{exit.status}</span>
      </div>
      <p className="panel-note">{exit.message}</p>
      <div className="metric-grid">
        <Metric label="Open positions" value={String(exit.openPositionCount)} />
        <Metric label="Triggered" value={String(exit.triggeredCount)} />
        <Metric label="Simulated" value={String(exit.simulatedCount)} />
        <Metric label="Refused" value={String(exit.refusedCount)} />
      </div>
      <Disclosure
        title={
          exit.intents.length === 1
            ? "View 1 exit intent"
            : `View ${exit.intents.length} exit intents`
        }
      >
        <DashboardDataGrid
          rows={exit.intents}
          columns={columns}
          emptyTitle="No exit intents"
          emptyBody="Exit intents will appear after open positions cross configured exit thresholds."
          getRowId={(intent) => intent.id}
          searchPlaceholder="Filter exit intents"
        />
      </Disclosure>
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
      <Disclosure
        title={
          brokerHistory.checkpoints.length === 1
            ? "View 1 broker checkpoint"
            : `View ${brokerHistory.checkpoints.length} broker checkpoints`
        }
      >
        <DashboardDataGrid
          rows={brokerHistory.checkpoints}
          columns={columns}
          emptyTitle="No broker checkpoints"
          emptyBody="Alpaca broker history checkpoints will appear after order, fill, position, or bar imports run."
          getRowId={(checkpoint) => checkpoint.id}
          searchPlaceholder="Filter broker checkpoints"
        />
      </Disclosure>
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

function jsonSummary(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0)) {
    return "";
  }
  const text = JSON.stringify(value);
  return text.length > 600 ? `${text.slice(0, 600)}...` : text;
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
  if (["blocked", "failed", "rate_limited", "refused"].includes(status)) {
    return "blocked";
  }
  if (
    [
      "waiting",
      "idle",
      "skipped",
      "empty",
      "no_candidates_passed",
      "no_candidates",
      "no_scores",
      "no_votes",
      "no_consensus",
      "no_intents",
      "no_positions",
      "no_triggers",
    ].includes(status)
  ) {
    return "idle";
  }
  return "ok";
}

function KillSwitchControl({ active }: { active: boolean }) {
  const [reason, setReason] = useState("operator stop");
  const [confirmed, setConfirmed] = useState(false);
  const [open, setOpen] = useState(false);
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
    setOpen(false);
  }

  return (
    <div className="danger-zone">
      <div>
        <p className="section-label">Emergency control</p>
        <h2 id="kill-switch-title">Kill Switch</h2>
        <p>
          Stops new live orders and asks the backend to cancel known open live orders.
          Dry-run records can still be reviewed.
        </p>
      </div>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Trigger asChild>
          <button className="button danger" disabled={active || state.status === "submitting"} type="button">
            {active ? "Kill switch active" : "Review kill switch"}
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content" aria-describedby="kill-switch-dialog-body">
            <div className="dialog-heading">
              <AlertTriangle aria-hidden="true" size={22} strokeWidth={2.4} />
              <div>
                <Dialog.Title>Activate kill switch</Dialog.Title>
                <Dialog.Description id="kill-switch-dialog-body">
                  This disables live trading and asks the backend to cancel known live orders.
                </Dialog.Description>
              </div>
            </div>
            <form className="dialog-form" onSubmit={onSubmit}>
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
              <div className="dialog-actions">
                <Dialog.Close asChild>
                  <button className="button" type="button">
                    Cancel
                  </button>
                </Dialog.Close>
                <button
                  className="button danger"
                  disabled={!confirmed || active || state.status === "submitting"}
                  type="submit"
                >
                  {state.status === "submitting" ? "Activating" : "Activate kill switch"}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      {state.status === "done" || state.status === "error" ? (
        <p className="status-message">{state.message}</p>
      ) : null}
    </div>
  );
}
