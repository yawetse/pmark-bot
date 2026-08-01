"use client";

import { FormEvent, useMemo, useState } from "react";
import { CalendarClock, Landmark, Plus, Save, ShieldAlert, Trash2 } from "lucide-react";

import type { ConfigSnapshot } from "@/components/dashboard/config-controls";
import { dashboardApi } from "@/lib/api";

type FundingCadence = "weekly" | "monthly" | "low_balance";
type FundingVenue = "alpaca" | "polymarket_us";
type FundingProvider = "openai" | "claude";
type FundingMode = "observe" | "direct";

type FundingSchedule = {
  id: string;
  enabled: boolean;
  venue: FundingVenue;
  model_provider: FundingProvider;
  cadence: FundingCadence;
  execution_mode: FundingMode;
  direction: "deposit" | "withdrawal";
  amount_usd?: string;
  target_balance_usd?: string;
  iso_weekday?: number;
  day_of_month?: number;
};

type FundingConfig = {
  emergency_stop: boolean;
  direct_transfers_enabled: boolean;
  max_transfer_usd: string;
  max_monthly_transfer_usd: string;
  timezone: "America/New_York";
  missing_after_business_days: 4;
  schedules: FundingSchedule[];
};

type EditorState = {
  index: number | null;
  schedule: FundingSchedule;
};

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; version: string }
  | { status: "error"; message: string };

const EMPTY_SCHEDULE: FundingSchedule = {
  id: "",
  enabled: true,
  venue: "alpaca",
  model_provider: "openai",
  cadence: "weekly",
  execution_mode: "observe",
  direction: "deposit",
  amount_usd: "100.00",
  iso_weekday: 5,
};

export function FundingControls({
  initialSnapshot,
  onSnapshotChange,
}: {
  initialSnapshot: ConfigSnapshot;
  onSnapshotChange?: (snapshot: ConfigSnapshot) => void;
}) {
  const [funding, setFunding] = useState(() => fundingFromSnapshot(initialSnapshot));
  const [currentVersion, setCurrentVersion] = useState(initialSnapshot.version);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [directConfirmed, setDirectConfirmed] = useState(false);
  const directScheduleCount = useMemo(
    () => funding.schedules.filter((schedule) => schedule.execution_mode === "direct").length,
    [funding.schedules],
  );

  async function saveFunding(next: FundingConfig): Promise<boolean> {
    setSaveState({ status: "saving" });
    const result = await dashboardApi<{ new_version?: string }>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: initialSnapshot.environment,
        expected_version: currentVersion === "bootstrap" ? null : currentVersion,
        patches: [{ op: "replace", path: "funding", value: next }],
      }),
    });
    if (!result.ok) {
      setSaveState({ status: "error", message: result.message });
      return false;
    }
    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (refreshed.ok) {
      setFunding(fundingFromSnapshot(refreshed.data));
      setCurrentVersion(refreshed.data.version);
      setSaveState({ status: "saved", version: refreshed.data.version });
      onSnapshotChange?.(refreshed.data);
      return true;
    }
    const version = result.data.new_version ?? currentVersion;
    setFunding(next);
    setCurrentVersion(version);
    setSaveState({ status: "saved", version });
    window.location.reload();
    return true;
  }

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    const normalized = normalizeSchedule(editor.schedule);
    if (!normalized.id.trim()) {
      setSaveState({ status: "error", message: "Schedule name is required." });
      return;
    }
    const duplicate = funding.schedules.some(
      (schedule, index) => schedule.id === normalized.id && index !== editor.index,
    );
    if (duplicate) {
      setSaveState({ status: "error", message: "Schedule names must be unique." });
      return;
    }
    const schedules = [...funding.schedules];
    if (editor.index === null) schedules.push(normalized);
    else schedules[editor.index] = normalized;
    if (await saveFunding({ ...funding, schedules })) setEditor(null);
  }

  async function setScheduleEnabled(index: number, enabled: boolean) {
    const schedules = funding.schedules.map((schedule, scheduleIndex) =>
      scheduleIndex === index ? { ...schedule, enabled } : schedule,
    );
    await saveFunding({ ...funding, schedules });
  }

  async function removeSchedule(index: number) {
    await saveFunding({
      ...funding,
      schedules: funding.schedules.filter((_, scheduleIndex) => scheduleIndex !== index),
    });
  }

  async function saveSafetyControls() {
    if (funding.direct_transfers_enabled && !directConfirmed) {
      setSaveState({
        status: "error",
        message: "Confirm the direct-transfer controls before enabling them.",
      });
      return;
    }
    await saveFunding(funding);
  }

  return (
    <section className="panel funding-controls" aria-labelledby="funding-controls-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Account funding</p>
          <h2 id="funding-controls-title">Recurring deposits</h2>
        </div>
        <span className={`status ${funding.direct_transfers_enabled ? "waiting" : "ok"}`}>
          {funding.direct_transfers_enabled ? "direct configured" : "observe first"}
        </span>
      </div>

      <div className="funding-boundary-note">
        <Landmark aria-hidden="true" size={20} />
        <div>
          <strong>Venue-managed funding</strong>
          <p>
            Alpaca and Polymarket report deposits and withdrawals. Bank relationships stay at the
            venue. Plaid is not required.
          </p>
        </div>
      </div>

      <div className="funding-schedule-heading">
        <div>
          <h3>Schedules</h3>
          <p>Track Weekly, Monthly, or Low balance deposits for each model account.</p>
        </div>
        <button
          className="button primary"
          onClick={() => setEditor({ index: null, schedule: { ...EMPTY_SCHEDULE } })}
          type="button"
        >
          <Plus aria-hidden="true" size={15} /> Add schedule
        </button>
      </div>

      <div className="funding-schedule-list">
        {funding.schedules.length ? funding.schedules.map((schedule, index) => (
          <article className={`funding-schedule-card ${schedule.cadence}`} key={schedule.id}>
            <div className="funding-schedule-marker" aria-hidden="true" />
            <div className="funding-schedule-copy">
              <div>
                <strong>{schedule.id}</strong>
                <span className={`status ${schedule.enabled ? "ok" : "idle"}`}>
                  {schedule.enabled ? "enabled" : "disabled"}
                </span>
              </div>
              <p>{scheduleSummary(schedule)}</p>
              <small>
                {schedule.venue === "polymarket_us" ? "Polymarket US, observe-only" : "Alpaca"}
                {` · ${providerLabel(schedule.model_provider)} · ${modeLabel(schedule.execution_mode)}`}
              </small>
            </div>
            <div className="funding-schedule-actions">
              <button className="button" onClick={() => setEditor({ index, schedule: { ...schedule } })} type="button">Edit</button>
              <button className="button" onClick={() => void setScheduleEnabled(index, !schedule.enabled)} type="button">
                {schedule.enabled ? "Disable" : "Enable"}
              </button>
              <button aria-label={`Remove ${schedule.id}`} className="icon-button" onClick={() => void removeSchedule(index)} type="button">
                <Trash2 aria-hidden="true" size={15} />
                <span className="sr-only">Remove</span>
              </button>
            </div>
          </article>
        )) : (
          <div className="funding-empty-state">
            <CalendarClock aria-hidden="true" size={22} />
            <strong>No funding schedules</strong>
            <p>Add a schedule to compare expected deposits with venue-confirmed activity.</p>
          </div>
        )}
      </div>

      {editor ? (
        <ScheduleEditor
          editor={editor}
          onCancel={() => setEditor(null)}
          onChange={(schedule) => setEditor((current) => current ? { ...current, schedule } : current)}
          onSubmit={saveSchedule}
        />
      ) : null}

      <section className="funding-safety-controls" aria-labelledby="funding-safety-title">
        <div className="funding-safety-heading">
          <ShieldAlert aria-hidden="true" size={20} />
          <div>
            <p className="section-label">Direct Alpaca ACH</p>
            <h3 id="funding-safety-title">Transfer safety controls</h3>
          </div>
        </div>
        {!funding.direct_transfers_enabled ? (
          <p className="funding-direct-disabled">Direct transfers are disabled. Tracking and alerts remain active.</p>
        ) : null}
        <div className="funding-safety-grid">
          <label className="checkbox-row">
            <input
              checked={funding.emergency_stop}
              onChange={(event) => setFunding({ ...funding, emergency_stop: event.target.checked })}
              type="checkbox"
            />
            <span>Funding emergency stop</span>
          </label>
          <label className="checkbox-row">
            <input
              checked={funding.direct_transfers_enabled}
              onChange={(event) => {
                setFunding({ ...funding, direct_transfers_enabled: event.target.checked });
                setDirectConfirmed(false);
              }}
              type="checkbox"
            />
            <span>Enable direct incoming ACH</span>
          </label>
          <label>
            Per-transfer limit
            <input min="0" onChange={(event) => setFunding({ ...funding, max_transfer_usd: event.target.value })} step="0.01" type="number" value={funding.max_transfer_usd} />
          </label>
          <label>
            Monthly limit
            <input min="0" onChange={(event) => setFunding({ ...funding, max_monthly_transfer_usd: event.target.value })} step="0.01" type="number" value={funding.max_monthly_transfer_usd} />
          </label>
        </div>
        {funding.direct_transfers_enabled ? (
          <label className="checkbox-row funding-direct-confirmation">
            <input checked={directConfirmed} onChange={(event) => setDirectConfirmed(event.target.checked)} type="checkbox" />
            <span>I confirmed the Alpaca Broker account, ACH relationship, schedule, and both limits.</span>
          </label>
        ) : null}
        <div className="funding-safety-footer">
          <span>{directScheduleCount} direct schedule{directScheduleCount === 1 ? "" : "s"}</span>
          <button className="button primary" disabled={saveState.status === "saving"} onClick={() => void saveSafetyControls()} type="button">
            <Save aria-hidden="true" size={15} /> {saveState.status === "saving" ? "Saving" : "Save funding controls"}
          </button>
        </div>
      </section>

      {saveState.status === "saved" ? <p className="status-message">Saved version {saveState.version}. Applies on the next funding tick.</p> : null}
      {saveState.status === "error" ? <p className="status-message" role="alert">{saveState.message}</p> : null}
    </section>
  );
}

function ScheduleEditor({ editor, onCancel, onChange, onSubmit }: {
  editor: EditorState;
  onCancel: () => void;
  onChange: (schedule: FundingSchedule) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const schedule = editor.schedule;
  function patch(values: Partial<FundingSchedule>) { onChange(normalizeSchedule({ ...schedule, ...values })); }
  return (
    <form className="funding-schedule-editor" onSubmit={onSubmit}>
      <div className="funding-editor-heading">
        <div><p className="section-label">{editor.index === null ? "New schedule" : "Edit schedule"}</p><h3>{editor.index === null ? "Add recurring funding" : schedule.id}</h3></div>
        <button className="button" onClick={onCancel} type="button">Cancel</button>
      </div>
      <div className="funding-editor-grid">
        <label>Schedule name<input onChange={(event) => patch({ id: event.target.value })} required value={schedule.id} /></label>
        <label>Account<select onChange={(event) => patch({ model_provider: event.target.value as FundingProvider })} value={schedule.model_provider}><option value="openai">OpenAI</option><option value="claude">Claude</option></select></label>
        <label>Venue<select onChange={(event) => patch({ venue: event.target.value as FundingVenue, execution_mode: event.target.value === "polymarket_us" ? "observe" : schedule.execution_mode })} value={schedule.venue}><option value="alpaca">Alpaca</option><option value="polymarket_us">Polymarket US, observe-only</option></select></label>
        <label>Cadence<select onChange={(event) => patch({ cadence: event.target.value as FundingCadence })} value={schedule.cadence}><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="low_balance">Low balance</option></select></label>
        <label>Direction<select onChange={(event) => patch({ direction: event.target.value as "deposit" | "withdrawal", execution_mode: event.target.value === "withdrawal" ? "observe" : schedule.execution_mode })} value={schedule.direction}><option value="deposit">Deposit</option><option value="withdrawal">Withdrawal</option></select></label>
        <label>Mode<select disabled={schedule.venue === "polymarket_us" || schedule.direction === "withdrawal"} onChange={(event) => patch({ execution_mode: event.target.value as FundingMode })} value={schedule.execution_mode}><option value="observe">Observe and alert</option><option value="direct">Direct Alpaca ACH</option></select></label>
        {schedule.cadence === "weekly" ? <label>Weekday<select onChange={(event) => patch({ iso_weekday: Number(event.target.value) })} value={schedule.iso_weekday ?? 5}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => <option key={day} value={index + 1}>{day}</option>)}</select></label> : null}
        {schedule.cadence === "monthly" ? <label>Day of month<input max="31" min="1" onChange={(event) => patch({ day_of_month: Number(event.target.value) })} type="number" value={schedule.day_of_month ?? 1} /></label> : null}
        {schedule.cadence === "low_balance" ? <label>Target buying power<input min="0.01" onChange={(event) => patch({ target_balance_usd: event.target.value })} step="0.01" type="number" value={schedule.target_balance_usd ?? "500.00"} /></label> : <label>Expected amount<input min="0.01" onChange={(event) => patch({ amount_usd: event.target.value })} step="0.01" type="number" value={schedule.amount_usd ?? "100.00"} /></label>}
        {schedule.cadence === "low_balance" && schedule.execution_mode === "observe" ? <label>Expected amount<input min="0.01" onChange={(event) => patch({ amount_usd: event.target.value })} step="0.01" type="number" value={schedule.amount_usd ?? "100.00"} /></label> : null}
      </div>
      <button className="button primary" type="submit"><Save aria-hidden="true" size={15} /> Save schedule</button>
    </form>
  );
}

function normalizeSchedule(schedule: FundingSchedule): FundingSchedule {
  const next = { ...schedule };
  if (next.venue === "polymarket_us" || next.direction === "withdrawal") next.execution_mode = "observe";
  if (next.cadence === "weekly") {
    next.iso_weekday = next.iso_weekday ?? 5;
    delete next.day_of_month;
    delete next.target_balance_usd;
  } else if (next.cadence === "monthly") {
    next.day_of_month = next.day_of_month ?? 1;
    delete next.iso_weekday;
    delete next.target_balance_usd;
  } else {
    next.target_balance_usd = next.target_balance_usd ?? "500.00";
    delete next.iso_weekday;
    delete next.day_of_month;
    if (next.execution_mode === "direct") delete next.amount_usd;
    else next.amount_usd = next.amount_usd ?? "100.00";
  }
  return next;
}

function fundingFromSnapshot(snapshot: ConfigSnapshot): FundingConfig {
  const value = snapshot.settings.funding;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const raw = value as Partial<FundingConfig>;
    return {
      emergency_stop: Boolean(raw.emergency_stop),
      direct_transfers_enabled: Boolean(raw.direct_transfers_enabled),
      max_transfer_usd: String(raw.max_transfer_usd ?? "0.00"),
      max_monthly_transfer_usd: String(raw.max_monthly_transfer_usd ?? "0.00"),
      timezone: "America/New_York",
      missing_after_business_days: 4,
      schedules: Array.isArray(raw.schedules) ? raw.schedules.map(normalizeSchedule) : [],
    };
  }
  return { emergency_stop: false, direct_transfers_enabled: false, max_transfer_usd: "0.00", max_monthly_transfer_usd: "0.00", timezone: "America/New_York", missing_after_business_days: 4, schedules: [] };
}

function scheduleSummary(schedule: FundingSchedule): string {
  if (schedule.cadence === "weekly") return `Weekly on ${weekdayLabel(schedule.iso_weekday)} · ${money(schedule.amount_usd)}`;
  if (schedule.cadence === "monthly") return `Monthly on day ${schedule.day_of_month ?? 1} · ${money(schedule.amount_usd)}`;
  return `Low balance below ${money(schedule.target_balance_usd)}${schedule.amount_usd ? ` · expect ${money(schedule.amount_usd)}` : ""}`;
}

function weekdayLabel(value?: number): string { return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][(value ?? 5) - 1] ?? "Friday"; }
function money(value?: string): string { const parsed = Number(value); return Number.isFinite(parsed) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parsed) : "Amount unavailable"; }
function providerLabel(value: FundingProvider): string { return value === "openai" ? "OpenAI" : "Claude"; }
function modeLabel(value: FundingMode): string { return value === "direct" ? "Direct ACH" : "Observe and alert"; }
