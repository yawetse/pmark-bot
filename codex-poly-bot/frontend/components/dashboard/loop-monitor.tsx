"use client";

// REQ: REQ-UI-004, REQ-OBS-005

type LoopState = "ok" | "blocked" | "idle" | "waiting";

type LoopStatus = {
  state: LoopState;
  label: string;
  detail: string;
};

type LoopSchedule = {
  intervalSeconds: number;
  lastHeartbeatAt?: string | null;
  ageSeconds?: number | null;
  nextRunAt: string;
  secondsUntilNextRun: number;
  source?: string | null;
};

type LoopPhase = {
  id: string;
  label: string;
  state: LoopState;
  detail: string;
};

type LoopItem = {
  label: string;
  value: string;
  state: LoopState;
  detail?: string;
};

type LoopCalculation = {
  label: string;
  formula: string;
  value: string;
  state: LoopState;
};

type LoopGate = {
  label: string;
  value: string;
  state: LoopState;
};

export type LoopObservabilityView = {
  environment: string;
  generatedAt: string;
  status: LoopStatus;
  schedule: LoopSchedule;
  currentPhase: LoopPhase;
  stages: LoopPhase[];
  dataInputs: LoopItem[];
  prompts: LoopItem[];
  logic: LoopItem[];
  calculations: LoopCalculation[];
  gates: LoopGate[];
  records: {
    orderEvents: number;
    openOrders: number;
    auditEvents: number;
  };
};

export function LoopMonitor({
  loop,
  timeZone = "UTC",
}: {
  loop: LoopObservabilityView;
  timeZone?: string;
}) {
  return (
    <section className="operator-panel loop-monitor" aria-labelledby="loop-monitor-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Loop monitor</p>
          <h2 id="loop-monitor-title">What happens next</h2>
        </div>
        <span className={`status ${stateClass(loop.status.state)}`}>{loop.status.label}</span>
      </div>

      <div className="loop-current">
        <span className={`status-dot ${stateClass(loop.currentPhase.state)}`} aria-hidden="true" />
        <div>
          <strong>{loop.currentPhase.label}</strong>
          <p>{loop.currentPhase.detail}</p>
          <small>Snapshot generated {formatTime(loop.generatedAt, timeZone)} for {loop.environment}</small>
        </div>
      </div>

      <div className="loop-schedule-grid">
        <LoopMetric label="Next run" value={formatTime(loop.schedule.nextRunAt, timeZone)} />
        <LoopMetric label="Countdown" value={formatDuration(loop.schedule.secondsUntilNextRun)} />
        <LoopMetric label="Interval" value={`${loop.schedule.intervalSeconds}s`} />
        <LoopMetric label="Last heartbeat" value={formatTime(loop.schedule.lastHeartbeatAt, timeZone)} />
      </div>

      <ol className="loop-stage-list" aria-label="Loop stages">
        {loop.stages.map((stage, index) => (
          <li className={`loop-stage ${stateClass(stage.state)}`} key={stage.id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{stage.label}</strong>
              <p>{stage.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="loop-detail-grid">
        <LoopDetailSection title="Data in use" items={loop.dataInputs} />
        <LoopDetailSection title="Prompts" items={loop.prompts} />
        <LoopDetailSection title="Decision logic" items={loop.logic} />
        <LoopCalculationSection calculations={loop.calculations} />
        <LoopGateSection gates={loop.gates} />
        <section className="loop-detail-section" aria-labelledby="loop-records-title">
          <h3 id="loop-records-title">Records</h3>
          <div className="loop-record-grid">
            <LoopMetric label="Order events" value={String(loop.records.orderEvents)} />
            <LoopMetric label="Open orders" value={String(loop.records.openOrders)} />
            <LoopMetric label="Audit events" value={String(loop.records.auditEvents)} />
          </div>
        </section>
      </div>
    </section>
  );
}

function LoopDetailSection({ title, items }: { title: string; items: LoopItem[] }) {
  return (
    <section className="loop-detail-section" aria-labelledby={`loop-${slug(title)}-title`}>
      <h3 id={`loop-${slug(title)}-title`}>{title}</h3>
      <div className="loop-item-list">
        {items.map((item) => (
          <div className="loop-row" key={item.label}>
            <span className={`status-dot ${stateClass(item.state)}`} aria-hidden="true" />
            <div>
              <strong>{item.label}</strong>
              <p>{item.value}</p>
              {item.detail ? <small>{item.detail}</small> : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function LoopCalculationSection({ calculations }: { calculations: LoopCalculation[] }) {
  return (
    <section className="loop-detail-section" aria-labelledby="loop-calculations-title">
      <h3 id="loop-calculations-title">Calculations</h3>
      <div className="loop-item-list">
        {calculations.map((calculation) => (
          <div className="loop-row" key={calculation.label}>
            <span className={`status-dot ${stateClass(calculation.state)}`} aria-hidden="true" />
            <div>
              <strong>{calculation.label}</strong>
              <p>{calculation.formula}</p>
              <small>{calculation.value}</small>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function LoopGateSection({ gates }: { gates: LoopGate[] }) {
  return (
    <section className="loop-detail-section" aria-labelledby="loop-gates-title">
      <h3 id="loop-gates-title">Pre-trade gates</h3>
      <div className="loop-gate-grid">
        {gates.map((gate) => (
          <div className={`loop-gate ${stateClass(gate.state)}`} key={gate.label}>
            <span>{gate.label}</span>
            <strong>{gate.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function LoopMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="loop-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function stateClass(state: LoopState): LoopState {
  return state;
}

function formatTime(value: string | null | undefined, timeZone: string): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "not recorded";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(date);
}

function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) {
    return "unknown";
  }
  if (seconds <= 0) {
    return "due now";
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes === 0) {
    return `${remainder}s`;
  }
  return `${minutes}m ${remainder}s`;
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
