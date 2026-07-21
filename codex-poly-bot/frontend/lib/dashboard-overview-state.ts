import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type {
  OperationsSummaryView,
  OrderIntentView,
} from "@/components/dashboard/operations-view";
import type { AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-017, REQ-UI-018, REQ-UI-025

export type OverviewBlocker = {
  key: string;
  title: string;
  body: string;
  href: string;
  linkLabel: string;
  stage?: "scanner" | "reasoning" | "strategy" | "risk";
  recommendationPath?: AllowedConfigPath;
};

export type OverviewState =
  | {
      kind: "live";
      order: OrderIntentView | null;
      title: string;
      body: string;
    }
  | {
      kind: "attention";
      blockers: OverviewBlocker[];
      title: string;
      body: string;
    }
  | {
      kind: "clear";
      title: string;
      body: string;
    };

export type OverviewStateInput = {
  operations: OperationsSummaryView | null;
  marketData: MarketDataPullView | null;
  activeVenueLabels: string[];
  configReady: boolean;
  notificationsReady: boolean | null;
  criticalErrors: string[];
};

export function deriveOverviewState({
  operations,
  marketData,
  activeVenueLabels,
  configReady,
  notificationsReady,
  criticalErrors,
}: OverviewStateInput): OverviewState {
  const liveOrder = latestTickLiveOrder(operations);
  if (liveOrder.matched) {
    const order = liveOrder.order;
    const instrument = order?.instrumentId ? ` for ${order.instrumentId}` : "";
    return {
      kind: "live",
      order,
      title: "A live trade was placed",
      body: `The latest completed check submitted a real order${instrument}. Review the submission details in Activity.`,
    };
  }

  const blockers = overviewBlockers({
    operations,
    marketData,
    activeVenueLabels,
    configReady,
    notificationsReady,
    criticalErrors,
  });
  if (blockers.length) {
    return {
      kind: "attention",
      blockers: blockers.slice(0, 3),
      title: "A few things need attention",
      body: "The latest check stopped before a live order or a required operating setting is incomplete.",
    };
  }

  return {
    kind: "clear",
    title: "Everything looks clear",
    body: "The latest check completed without a live order or an operator blocker. The next check will use the current settings.",
  };
}

export function latestTickLiveOrder(operations: OperationsSummaryView | null): {
  matched: boolean;
  order: OrderIntentView | null;
} {
  const pipeline = latestCompletedPipeline(operations);
  const execution = operations?.execution?.latestRun;
  if (!pipeline || !execution || (execution.submittedCount ?? 0) < 1) {
    return { matched: false, order: null };
  }

  const eligibleOrder =
    execution.intents.find((intent) => isPlacedIntent(intent.status)) ?? null;
  if (!eligibleOrder) {
    return { matched: false, order: null };
  }
  const idsMatch = Boolean(
    execution.pipelineRunId && execution.pipelineRunId === pipeline.id,
  );
  const timestampsMatch = !execution.pipelineRunId && executionWithinPipeline(execution, pipeline);
  return {
    matched: idsMatch || timestampsMatch,
    order: idsMatch || timestampsMatch ? eligibleOrder : null,
  };
}

function latestCompletedPipeline(operations: OperationsSummaryView | null) {
  const runs = operations?.pipelineRuns ?? [];
  return runs.find((run) => Boolean(run.completedAt) || isTerminalStatus(run.status)) ?? null;
}

function executionWithinPipeline(
  execution: NonNullable<OperationsSummaryView["execution"]>["latestRun"],
  pipeline: OperationsSummaryView["pipelineRuns"][number],
): boolean {
  if (!execution) {
    return false;
  }
  const pipelineStart = timestamp(pipeline.startedAt);
  const pipelineEnd = timestamp(pipeline.completedAt) ?? pipelineStart;
  const executionTime = timestamp(execution.completedAt) ?? timestamp(execution.startedAt);
  if (pipelineStart === null || pipelineEnd === null || executionTime === null) {
    return false;
  }
  return executionTime >= pipelineStart && executionTime <= pipelineEnd;
}

function overviewBlockers({
  operations,
  marketData,
  activeVenueLabels,
  configReady,
  notificationsReady,
  criticalErrors,
}: OverviewStateInput): OverviewBlocker[] {
  const blockers: OverviewBlocker[] = [];
  if (criticalErrors.length) {
    blockers.push({
      key: "data",
      title: "Some dashboard data is unavailable",
      body: criticalErrors[0] ?? "One or more current checks could not be loaded.",
      href: "/dashboard/system",
      linkLabel: "Open system health",
    });
  }
  if (operations?.killSwitch === "active") {
    blockers.push({
      key: "kill-switch",
      title: "Emergency stop is active",
      body: "New live orders are blocked until the emergency stop is intentionally cleared.",
      href: "/dashboard/operations",
      linkLabel: "Review emergency stop",
    });
  }
  if (configReady && activeVenueLabels.length === 0) {
    blockers.push({
      key: "venues",
      title: "Choose a market to watch",
      body: "No venue is enabled, so the next check has no market source.",
      href: "/dashboard/config",
      linkLabel: "Open settings",
    });
  }
  if (notificationsReady === false) {
    blockers.push({
      key: "notifications",
      title: "Finish notification setup",
      body: "Add a valid recipient so a live trade can produce an operator alert.",
      href: "/dashboard/config",
      linkLabel: "Set recipient",
    });
  }

  const scanner = operations?.scanner;
  const scanned = Math.max(scanner?.candidateCount ?? 0, marketData?.candidateCount ?? 0);
  if (scanned > 0 && (scanner?.acceptedCount ?? 0) === 0) {
    const recommendationPath = scannerRecommendationPath(operations);
    blockers.push({
      key: "scanner",
      title: "Market filters stopped the latest check",
      body: `${scanner?.rejectedCount ?? scanned} market${scanned === 1 ? "" : "s"} stopped before model scoring.`,
      href: "/dashboard/activity",
      linkLabel: "Review the funnel",
      stage: "scanner",
      recommendationPath,
    });
  }

  const reasoning = operations?.reasoning;
  if ((reasoning?.promptCount ?? 0) > 0 && (reasoning?.scoredCount ?? 0) === 0) {
    const recommendationPath = reasoningRecommendationPath(operations);
    blockers.push({
      key: "reasoning",
      title: "No candidate passed the confidence rule",
      body: `${reasoning?.skippedCount ?? 0} skipped and ${reasoning?.failedCount ?? 0} failed model checks were recorded.`,
      href: "/dashboard/activity",
      linkLabel: "Review the check",
      stage: "reasoning",
      recommendationPath,
    });
  }

  const strategy = operations?.strategyConsensus;
  if ((strategy?.voteCount ?? 0) > 0 && (strategy?.approvedCount ?? 0) === 0) {
    blockers.push({
      key: "strategy",
      title: "Strategy checks did not approve a trade",
      body: `${strategy?.refusedCount ?? strategy?.voteCount ?? 0} strategy vote${strategy?.voteCount === 1 ? "" : "s"} stopped.`,
      href: "/dashboard/activity",
      linkLabel: "Review the check",
      stage: "strategy",
    });
  }

  const execution = operations?.execution;
  if (
    (execution?.intentCount ?? 0) > 0 &&
    (execution?.submittedCount ?? 0) + (execution?.simulatedCount ?? 0) === 0
  ) {
    blockers.push({
      key: "risk",
      title: "Risk checks stopped every order plan",
      body: `${execution?.refusedCount ?? execution?.intentCount ?? 0} order plan${execution?.intentCount === 1 ? "" : "s"} did not reach simulation or submission.`,
      href: "/dashboard/operations",
      linkLabel: "Open detailed operations",
      stage: "risk",
    });
  }
  return dedupeBlockers(blockers);
}

function scannerRecommendationPath(
  operations: OperationsSummaryView | null,
): AllowedConfigPath | undefined {
  const pipeline = latestCompletedPipeline(operations);
  const run = operations?.scanner?.latestRun;
  if (!pipeline || !run || run.pipelineRunId !== pipeline.id) {
    return undefined;
  }
  const rejected = run.candidates.filter(
    (candidate) => candidate.refusalReason && candidate.status.toLowerCase() !== "accepted",
  );
  if (
    rejected.length === 0 ||
    rejected.some((candidate) => !isSpreadRejection(candidate.refusalReason ?? ""))
  ) {
    return undefined;
  }
  return recommendationPathForVenues(rejected.map((candidate) => candidate.venue), "spread");
}

function reasoningRecommendationPath(
  operations: OperationsSummaryView | null,
): AllowedConfigPath | undefined {
  const pipeline = latestCompletedPipeline(operations);
  const run = operations?.reasoning?.latestRun;
  if (!pipeline || !run || run.pipelineRunId !== pipeline.id) {
    return undefined;
  }
  const refused = run.outputs.filter((output) => output.refusalReason);
  if (
    refused.length === 0 ||
    refused.some((output) => !/confidence/i.test(output.refusalReason ?? ""))
  ) {
    return undefined;
  }
  return recommendationPathForVenues(refused.map((output) => output.venue), "confidence");
}

function recommendationPathForVenues(
  venues: string[],
  gate: "spread" | "confidence",
): AllowedConfigPath | undefined {
  const families = new Set(
    venues.map((venue) => (venue.toLowerCase().includes("alpaca") ? "alpaca" : "polymarket")),
  );
  if (families.size !== 1) {
    return undefined;
  }
  const family = [...families][0];
  if (gate === "spread") {
    return family === "alpaca" ? "scanner.alpaca.max_spread" : "scanner.polymarket.max_spread";
  }
  return family === "alpaca"
    ? "reasoning.alpaca.min_confidence"
    : "reasoning.polymarket.min_confidence";
}

function isSpreadRejection(reason: string): boolean {
  return /spread (?:too wide|limit|threshold)|maximum spread|max spread/i.test(reason);
}

function dedupeBlockers(blockers: OverviewBlocker[]): OverviewBlocker[] {
  const seen = new Set<string>();
  return blockers.filter((blocker) => {
    if (seen.has(blocker.key)) {
      return false;
    }
    seen.add(blocker.key);
    return true;
  });
}

function isPlacedIntent(status: string): boolean {
  return ["submitted", "filled", "partially_filled"].includes(status.toLowerCase());
}

function isTerminalStatus(status: string): boolean {
  return ["completed", "succeeded", "success", "failed", "blocked", "partial"].includes(
    status.toLowerCase(),
  );
}

function timestamp(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}
