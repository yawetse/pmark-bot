"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { FormEvent, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Bot,
  Clock,
  CircleHelp,
  DollarSign,
  Landmark,
  LineChart,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Disclosure, FormSection } from "@/components/dashboard/dashboard-primitives";
import { dashboardApi } from "@/lib/api";
import {
  ALLOWED_CONFIG_PATHS,
  CONFIG_PATH_DETAILS,
  isAllowedConfigPath,
} from "@/lib/config-paths";
import type { AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-022, REQ-ALP-014, REQ-NOT-006

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
  username?: string | null;
  config_owner?: string;
  version: string;
  settings: Record<string, unknown>;
  degraded?: boolean;
};

type SaveState =
  | { status: "idle" }
  | { status: "saved"; version: string }
  | { status: "conflict"; currentVersion: string }
  | { status: "error"; message: string };

type LiveModeConfirmationState =
  | { status: "closed" }
  | {
      status: "open";
      confirmed: boolean;
      currentValue: unknown;
      nextValue: ConfigValue;
      setting: SettingDefinition;
      source: "advanced" | "preference";
    };

type TradingProfileConfirmationState = {
  open: boolean;
  confirmed: boolean;
};

type ConfigControlsProps = {
  initialSnapshot?: ConfigSnapshot;
  loadError?: string;
  onSnapshotChange?: (snapshot: ConfigSnapshot) => void;
};

type SettingUnit = "count" | "hours" | "minutes" | "percent" | "seconds" | "usd";

type SettingBase = {
  path: AllowedConfigPath;
  stage: string;
  note?: string;
};

type SettingDefinition = SettingBase &
  (
    | { kind: "switch"; fallback?: boolean }
    | {
        kind: "range";
        fallback: number;
        max: number;
        min: number;
        step: number;
        unit: SettingUnit;
        displayMultiplier?: number;
      }
    | {
        kind: "number";
        fallback: number;
        min?: number;
        step?: number;
        unit: SettingUnit;
        displayMultiplier?: number;
      }
    | {
        kind: "select";
        fallback: string;
        options: Array<{ label: string; value: string }>;
      }
    | { kind: "text"; fallback: string }
  );

type SettingSection = {
  title: string;
  body: string;
  icon: LucideIcon;
  settings: SettingDefinition[];
};

type GlossaryTerm = {
  term: string;
  definition: string;
};

const CONFIG_GLOSSARY: Array<GlossaryTerm & { matches: string[] }> = [
  {
    term: "Gamma",
    definition: "Polymarket's market metadata API. The app uses it to find active markets and basic market details before deeper checks run.",
    matches: ["gamma"],
  },
  {
    term: "CLOB",
    definition: "Central limit order book. It is the venue's list of current buy and sell interest. The app uses it to estimate liquidity, price, and slippage.",
    matches: ["clob"],
  },
  {
    term: "Order book",
    definition: "The list of open bids and asks for a market. A stronger order book usually gives the app more reliable price and liquidity checks.",
    matches: ["order-book", "order book", "depth"],
  },
  {
    term: "Bid",
    definition: "The highest current price someone is offering to pay.",
    matches: ["bid"],
  },
  {
    term: "Ask",
    definition: "The lowest current price someone is willing to sell for.",
    matches: ["ask"],
  },
  {
    term: "Spread",
    definition: "The gap between the best bid and best ask. Wider spreads can make entry and exit prices worse.",
    matches: ["spread", "slippage"],
  },
  {
    term: "Scanner",
    definition: "The filtering stage that narrows raw market data down to candidates worth scoring. It runs before model scoring.",
    matches: ["scanner", "scan", "candidate", "candidates"],
  },
  {
    term: "Trading loop",
    definition: "One scheduled pass through market data, market filters, model scoring, strategy checks, risk gates, and alerts.",
    matches: ["trading loop", "loop", "run schedule"],
  },
  {
    term: "Candidate",
    definition: "A market or symbol that has passed enough early checks to be considered by later stages.",
    matches: ["candidate", "candidates"],
  },
  {
    term: "Liquidity",
    definition: "How much trading interest is available near the current price. Low liquidity can make orders harder or more expensive to fill.",
    matches: ["liquidity"],
  },
  {
    term: "Volume",
    definition: "How much has traded over a period of time. Higher volume can make pricing signals more reliable.",
    matches: ["volume"],
  },
  {
    term: "Resolution",
    definition: "For a prediction market, this is when the event outcome is expected to settle.",
    matches: ["resolution"],
  },
  {
    term: "Venue",
    definition: "A trading destination such as Polymarket US, Polymarket International, or Alpaca.",
    matches: ["venue", "polymarket", "alpaca"],
  },
  {
    term: "Live trading",
    definition: "Allows real orders only after other gates pass. Turning it on does not bypass venue, credential, risk, or emergency-stop checks.",
    matches: ["live trading", "live mode", "live_enabled", "live account"],
  },
  {
    term: "Paper account",
    definition: "A simulated brokerage account used for testing without placing real trades.",
    matches: ["paper"],
  },
  {
    term: "Broker",
    definition: "The account provider that can receive stock or ETF orders. In this app, Alpaca is the broker.",
    matches: ["broker", "brokerage"],
  },
  {
    term: "Risk gate",
    definition: "The stage that blocks orders when size, loss, position count, allocation, slippage, or safety controls are outside the configured limits.",
    matches: ["risk gate", "risk", "gate"],
  },
  {
    term: "Position",
    definition: "An active holding or exposure created by a prior trade.",
    matches: ["position", "positions", "exposure"],
  },
  {
    term: "Daily loss limit",
    definition: "A loss threshold for the day. When the threshold is reached, the app blocks new orders for that scope.",
    matches: ["daily loss"],
  },
  {
    term: "Allocation",
    definition: "The share of model capital assigned to one symbol. Lower allocation limits keep a single name from taking too much of the portfolio.",
    matches: ["allocation"],
  },
  {
    term: "Market order",
    definition: "An order that tries to fill at the best available price now. It can move away from the expected price when liquidity is thin.",
    matches: ["market order"],
  },
  {
    term: "Slippage",
    definition: "The difference between the expected price and the actual fill price. This setting limits how much worse the fill can be.",
    matches: ["slippage"],
  },
  {
    term: "Reasoning",
    definition: "The model-scoring stage. The app asks configured AI providers to evaluate candidates that survive market filters.",
    matches: ["reasoning", "model", "prompt"],
  },
  {
    term: "Confidence",
    definition: "The model's reported certainty. Higher minimum confidence means fewer candidates move forward.",
    matches: ["confidence"],
  },
  {
    term: "Edge",
    definition: "The gap between the model's estimated probability and the market price. Higher minimum edge means the app needs a stronger difference before it acts.",
    matches: ["edge"],
  },
  {
    term: "Strategy",
    definition: "A rule family that decides how a candidate can become a trade idea, such as convergence, arbitrage, or stock momentum.",
    matches: ["strategy", "strategies", "momentum", "mean reversion", "gap", "volatility"],
  },
  {
    term: "Budget",
    definition: "A cap on model spend. When the cap is used, the app stops sending new scoring requests for that provider.",
    matches: ["budget", "spend"],
  },
  {
    term: "Alert",
    definition: "A notification the app can send when a configured condition is met, such as a live trade, daily loss, model spend, or venue issue.",
    matches: ["alert", "alerts", "email", "notification", "notifications"],
  },
  {
    term: "Threshold",
    definition: "The value that must be crossed before an alert or gate takes action.",
    matches: ["threshold"],
  },
  {
    term: "Alert cooldown",
    definition: "The quiet period before the same alert can be sent again.",
    matches: ["cooldown"],
  },
  {
    term: "Digest",
    definition: "A scheduled summary email rather than an immediate alert.",
    matches: ["digest"],
  },
  {
    term: "UTC",
    definition: "Coordinated Universal Time. Daily digest schedules use UTC rather than your local time zone.",
    matches: ["utc"],
  },
  {
    term: "Preset",
    definition: "A saved group of stock symbols, such as an index list, that can be reused for Alpaca scanning.",
    matches: ["preset", "presets"],
  },
  {
    term: "Symbol",
    definition: "A stock or ETF ticker, such as SPY or QQQ.",
    matches: ["symbol", "symbols", "ticker"],
  },
];

const VENUE_OPTIONS = [
  { label: "Polymarket US", value: "polymarket_us" },
  { label: "Polymarket International", value: "polymarket_international" },
  { label: "Alpaca", value: "alpaca" },
];

const ACCOUNT_MODE_OPTIONS = [
  { label: "Paper", value: "paper" },
  { label: "Live", value: "live" },
];

const OPENAI_SCORING_MODEL_OPTIONS = [
  { label: "GPT-5 Mini", value: "gpt-5-mini" },
  { label: "GPT-5 Nano", value: "gpt-5-nano" },
];

const ACTIVE_STOCK_PROFILE = "active_stock_day_trader";

const PREFERENCE_SECTIONS: SettingSection[] = [
  {
    title: "Trading Access",
    body: "Controls whether the app can evaluate venues and whether approved orders can reach a live account.",
    icon: Landmark,
    settings: [
      { path: "live_enabled", kind: "switch", fallback: false, stage: "Trade gate" },
      {
        path: "default_selected_venue",
        kind: "select",
        fallback: "polymarket_us",
        options: VENUE_OPTIONS,
        stage: "Venue selection",
      },
      { path: "venues.polymarket_us.enabled", kind: "switch", fallback: true, stage: "Scan" },
      { path: "venues.polymarket_international.enabled", kind: "switch", fallback: false, stage: "Scan" },
      { path: "venues.alpaca.enabled", kind: "switch", fallback: false, stage: "Scan" },
      {
        path: "alpaca.account_mode",
        kind: "select",
        fallback: "paper",
        options: ACCOUNT_MODE_OPTIONS,
        stage: "Broker account",
      },
      {
        path: "trading_loop_interval_seconds",
        kind: "range",
        fallback: 900,
        min: 5,
        max: 3600,
        step: 5,
        unit: "seconds",
        stage: "Run schedule",
      },
    ],
  },
  {
    title: "Market Scan",
    body: "Controls how many markets and symbols enter the pipeline before the model or risk gates run.",
    icon: LineChart,
    settings: [
      {
        path: "scanner.polymarket.market_data_limit",
        kind: "range",
        fallback: 100,
        min: 1,
        max: 250,
        step: 1,
        unit: "count",
        stage: "Market data",
        note: "This is the control that changes how many Polymarket candidates are considered before market filters run.",
      },
      {
        path: "scanner.polymarket.min_depth",
        kind: "number",
        fallback: 500,
        min: 0,
        step: 50,
        unit: "count",
        stage: "Market filter",
      },
      {
        path: "scanner.polymarket.min_liquidity",
        kind: "number",
        fallback: 500,
        min: 0,
        step: 50,
        unit: "count",
        stage: "Market filter",
      },
      {
        path: "scanner.polymarket.max_spread",
        kind: "range",
        fallback: 5,
        min: 0,
        max: 20,
        step: 0.1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Market filter",
      },
      {
        path: "scanner.polymarket.min_volume",
        kind: "number",
        fallback: 0,
        min: 0,
        step: 100,
        unit: "count",
        stage: "Market filter",
      },
      {
        path: "scanner.polymarket.min_hours_to_resolution",
        kind: "range",
        fallback: 4,
        min: 0,
        max: 168,
        step: 1,
        unit: "hours",
        stage: "Market filter",
      },
      {
        path: "scanner.polymarket.max_hours_to_resolution",
        kind: "range",
        fallback: 168,
        min: 1,
        max: 720,
        step: 1,
        unit: "hours",
        stage: "Market filter",
      },
      {
        path: "scanner.alpaca.min_quote_liquidity",
        kind: "number",
        fallback: 0.5,
        min: 0,
        step: 1,
        unit: "count",
        stage: "Stock filter",
      },
      {
        path: "scanner.alpaca.max_spread",
        kind: "range",
        fallback: 1,
        min: 0.01,
        max: 5,
        step: 0.01,
        unit: "usd",
        stage: "Stock filter",
      },
      {
        path: "scanner.alpaca.min_history_bars",
        kind: "range",
        fallback: 2,
        min: 1,
        max: 30,
        step: 1,
        unit: "count",
        stage: "Stock filter",
      },
    ],
  },
  {
    title: "Signals And Models",
    body: "Controls which signals run and how confident the model must be before a candidate can move forward.",
    icon: Bot,
    settings: [
      { path: "strategies.arbitrage.enabled", kind: "switch", fallback: true, stage: "Strategy" },
      { path: "strategies.convergence.enabled", kind: "switch", fallback: true, stage: "Strategy" },
      { path: "strategies.whale_copy.enabled", kind: "switch", fallback: false, stage: "Strategy" },
      {
        path: "reasoning.max_prompts_per_provider_per_run",
        kind: "range",
        fallback: 4,
        min: 1,
        max: 500,
        step: 1,
        unit: "count",
        stage: "Model budget",
      },
      {
        path: "llm.openai.settings.model",
        kind: "select",
        fallback: "gpt-5-mini",
        options: OPENAI_SCORING_MODEL_OPTIONS,
        stage: "Model cost",
        note: "Full GPT-5 is intentionally not available here. Existing saved full GPT-5 values are treated as GPT-5 Mini by the backend.",
      },
      {
        path: "reasoning.polymarket.min_confidence",
        kind: "range",
        fallback: 75,
        min: 0,
        max: 100,
        step: 1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Model scoring",
      },
      {
        path: "reasoning.polymarket.min_edge",
        kind: "range",
        fallback: 7,
        min: 0,
        max: 30,
        step: 0.5,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Strategy gate",
      },
      {
        path: "reasoning.alpaca.min_confidence",
        kind: "range",
        fallback: 60,
        min: 0,
        max: 100,
        step: 1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Model scoring",
      },
      {
        path: "reasoning.alpaca.min_edge",
        kind: "range",
        fallback: 2,
        min: 0,
        max: 20,
        step: 0.5,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Strategy gate",
      },
      { path: "scanner.alpaca.strategies.momentum.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
      { path: "scanner.alpaca.strategies.mean_reversion.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
      { path: "scanner.alpaca.strategies.gap.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
      { path: "scanner.alpaca.strategies.liquidity.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
      { path: "scanner.alpaca.strategies.volatility.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
      { path: "scanner.alpaca.strategies.unusual_volume.enabled", kind: "switch", fallback: true, stage: "Stock signal" },
    ],
  },
  {
    title: "Risk Limits",
    body: "Controls the order-size and loss checks that run before an order can be placed.",
    icon: ShieldCheck,
    settings: [
      { path: "risk.polymarket.max_position_usd", kind: "number", fallback: 25, min: 0, step: 1, unit: "usd", stage: "Risk gate" },
      { path: "risk.polymarket.max_daily_loss_usd", kind: "number", fallback: 100, min: 0, step: 1, unit: "usd", stage: "Risk gate" },
      {
        path: "risk.polymarket.max_open_positions",
        kind: "range",
        fallback: 5,
        min: 1,
        max: 100,
        step: 1,
        unit: "count",
        stage: "Risk gate",
      },
      {
        path: "risk.polymarket.market_order_slippage_threshold",
        kind: "range",
        fallback: 2,
        min: 0,
        max: 10,
        step: 0.1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Execution gate",
      },
      { path: "risk.alpaca.max_position_usd", kind: "number", fallback: 100, min: 0, step: 1, unit: "usd", stage: "Risk gate" },
      { path: "risk.alpaca.max_daily_loss_usd", kind: "number", fallback: 250, min: 0, step: 1, unit: "usd", stage: "Risk gate" },
      {
        path: "risk.alpaca.max_open_positions",
        kind: "range",
        fallback: 10,
        min: 1,
        max: 100,
        step: 1,
        unit: "count",
        stage: "Risk gate",
      },
      {
        path: "risk.alpaca.max_portfolio_allocation_per_symbol",
        kind: "range",
        fallback: 10,
        min: 1,
        max: 100,
        step: 1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Risk gate",
      },
      {
        path: "risk.alpaca.market_order_slippage_threshold",
        kind: "range",
        fallback: 0.5,
        min: 0,
        max: 10,
        step: 0.1,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Execution gate",
      },
      {
        path: "exit.alpaca.profit_target_pct",
        kind: "range",
        fallback: 2,
        min: 0.25,
        max: 20,
        step: 0.25,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Stock exit",
      },
      {
        path: "exit.alpaca.stop_loss_pct",
        kind: "range",
        fallback: 1,
        min: 0.25,
        max: 10,
        step: 0.25,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Stock exit",
      },
      {
        path: "exit.alpaca.trailing_stop_pct",
        kind: "range",
        fallback: 1,
        min: 0.25,
        max: 10,
        step: 0.25,
        unit: "percent",
        displayMultiplier: 100,
        stage: "Stock exit",
      },
      {
        path: "exit.alpaca.max_position_age_hours",
        kind: "range",
        fallback: 6,
        min: 1,
        max: 24,
        step: 1,
        unit: "hours",
        stage: "Stock exit",
      },
      {
        path: "exit.alpaca.market_hours_only",
        kind: "switch",
        fallback: true,
        stage: "Stock session",
      },
      {
        path: "exit.alpaca.close_before_market_close_minutes",
        kind: "range",
        fallback: 15,
        min: 1,
        max: 120,
        step: 1,
        unit: "minutes",
        stage: "Stock session",
      },
    ],
  },
  {
    title: "Budgets And Alerts",
    body: "Controls model spend caps, alert thresholds, repeated alert timing, and trade emails.",
    icon: Bell,
    settings: [
      { path: "llm.openai.budget_usd", kind: "number", fallback: 20, min: 0, step: 1, unit: "usd", stage: "24-hour budget" },
      { path: "llm.claude.budget_usd", kind: "number", fallback: 20, min: 0, step: 1, unit: "usd", stage: "24-hour budget" },
      { path: "notifications.email_on_trade_placed", kind: "switch", fallback: false, stage: "Alerts" },
      { path: "notifications.thresholds.daily_loss_usd", kind: "number", fallback: 100, min: 0, step: 1, unit: "usd", stage: "Alerts" },
      { path: "notifications.thresholds.model_spend_usd", kind: "number", fallback: 20, min: 0, step: 1, unit: "usd", stage: "Alerts" },
      {
        path: "notifications.thresholds.venue_degradation_minutes",
        kind: "range",
        fallback: 15,
        min: 1,
        max: 240,
        step: 1,
        unit: "minutes",
        stage: "Alerts",
      },
      {
        path: "notifications.cooldown_seconds",
        kind: "range",
        fallback: 3600,
        min: 60,
        max: 86400,
        step: 60,
        unit: "seconds",
        stage: "Alerts",
      },
      { path: "notifications.digest_schedule_utc", kind: "text", fallback: "13:00", stage: "Daily digest" },
    ],
  },
];

export function ConfigControls({
  initialSnapshot,
  loadError,
  onSnapshotChange,
}: ConfigControlsProps) {
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
  const [currentVersion, setCurrentVersion] = useState(initialSnapshot?.version ?? "");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [pendingDrafts, setPendingDrafts] = useState<Partial<Record<AllowedConfigPath, ConfigValue>>>({});
  const [recipientEmailDraft, setRecipientEmailDraft] = useState(() =>
    recipientEmailForOwner(
      valueAtPath(initialSnapshot?.settings, "notifications.recipients"),
      initialSnapshot,
    ),
  );
  const [liveModeConfirmation, setLiveModeConfirmation] = useState<LiveModeConfirmationState>({
    status: "closed",
  });
  const [profileConfirmation, setProfileConfirmation] = useState<TradingProfileConfirmationState>({
    open: false,
    confirmed: false,
  });

  if (!initialSnapshot) {
    return (
      <section className="panel config-preferences-panel config-unavailable" aria-labelledby="config-unavailable-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">Settings</p>
            <h2 id="config-unavailable-title">Settings are unavailable</h2>
          </div>
          <span className="status blocked">read only</span>
        </div>
        <p className="status-message" role="status">
          {loadError ?? "The current saved config could not be loaded."} No settings can be changed until a versioned snapshot is available.
        </p>
      </section>
    );
  }
  const snapshot = initialSnapshot;
  const selectedDetail = CONFIG_PATH_DETAILS[path];
  const currentValue = valueAtPath(settings, path);
  const resolvedSymbols = symbolsFromValue(valueAtPath(settings, "alpaca.symbol_universe"));
  const presetMetadata = presetMetadataFromValue(valueAtPath(settings, "alpaca.preset_metadata"));
  const refreshEnabled = valueAtPath(settings, "alpaca.preset_refresh.enabled");
  const refreshCadence = valueAtPath(settings, "alpaca.preset_refresh.cadence_hours");
  const staleAfter = valueAtPath(settings, "alpaca.preset_refresh.stale_after_hours");
  const selectedVenue = String(valueAtPath(settings, "default_selected_venue") ?? "polymarket_us");
  const commonSettings = commonSettingsForVenue(selectedVenue);
  const savedRecipientEmail = recipientEmailForOwner(
    valueAtPath(settings, "notifications.recipients"),
    initialSnapshot,
  );
  const activeStockProfileApplied = activeStockProfileIsApplied(settings);
  const liveTradingOn = Boolean(valueAtPath(settings, "live_enabled"));
  const alpacaAccountMode = String(valueAtPath(settings, "alpaca.account_mode") ?? "paper");

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

    const liveModeSetting = settingForPath(path);
    if (
      liveModeSetting &&
      requiresLiveModeConfirmation(liveModeSetting.path, currentValue, parsedValue.value)
    ) {
      openLiveModeConfirmation("advanced", liveModeSetting, currentValue, parsedValue.value);
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

  async function saveConfigPatch(patchPath: AllowedConfigPath, nextValue: ConfigValue): Promise<boolean> {
    return saveConfigPatches([{ path: patchPath, value: nextValue }]);
  }

  async function saveConfigPatches(patches: ConfigPatchDraft[]): Promise<boolean> {
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: snapshot.environment,
        expected_version: currentVersion === "bootstrap" ? null : currentVersion,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
      }),
    });

    if (!result.ok) {
      const currentVersion = parseCurrentVersion(result.message);
      if (result.status === 409 && currentVersion) {
        setSaveState({ status: "conflict", currentVersion });
        return false;
      }
      setSaveState({ status: "error", message: result.message });
      return false;
    }

    const savedVersion = result.data.new_version ?? currentVersion;
    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (refreshed.ok) {
      setSettings(refreshed.data.settings);
      setCurrentVersion(refreshed.data.version);
      syncStockUniverseDrafts(refreshed.data.settings);
      setRecipientEmailDraft(
        recipientEmailForOwner(
          valueAtPath(refreshed.data.settings, "notifications.recipients"),
          refreshed.data,
        ),
      );
      setValue(formatValueForInput(valueAtPath(refreshed.data.settings, path)));
      setSaveState({ status: "saved", version: refreshed.data.version });
      onSnapshotChange?.(refreshed.data);
      return true;
    }
    setSettings((currentSettings) =>
      patches.reduce(
        (nextSettings, patch) => valueAtUpdatedPath(nextSettings, patch.path, patch.value),
        currentSettings,
      ),
    );
    setCurrentVersion(savedVersion);
    setSaveState({ status: "saved", version: savedVersion });
    window.location.reload();
    return true;
  }

  async function applyActiveStockProfile() {
    if (!profileConfirmation.confirmed) {
      return;
    }
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: snapshot.environment,
        expected_version: currentVersion === "bootstrap" ? null : currentVersion,
        profile: ACTIVE_STOCK_PROFILE,
      }),
    });
    if (!result.ok) {
      const conflictingVersion = parseCurrentVersion(result.message);
      if (result.status === 409 && conflictingVersion) {
        setSaveState({ status: "conflict", currentVersion: conflictingVersion });
      } else {
        setSaveState({ status: "error", message: result.message });
      }
      return;
    }
    const savedVersion = result.data.new_version ?? currentVersion;
    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (!refreshed.ok) {
      setCurrentVersion(savedVersion);
      setSaveState({
        status: "error",
        message: `Saved profile version ${savedVersion}, but the updated settings could not be reloaded. Reload this page before making another change.`,
      });
      setProfileConfirmation({ open: false, confirmed: false });
      return;
    }
    setSettings(refreshed.data.settings);
    setCurrentVersion(refreshed.data.version);
    setPendingDrafts({});
    syncStockUniverseDrafts(refreshed.data.settings);
    setRecipientEmailDraft(
      recipientEmailForOwner(
        valueAtPath(refreshed.data.settings, "notifications.recipients"),
        refreshed.data,
      ),
    );
    setValue(formatValueForInput(valueAtPath(refreshed.data.settings, path)));
    setSaveState({ status: "saved", version: refreshed.data.version });
    onSnapshotChange?.(refreshed.data);
    setProfileConfirmation({ open: false, confirmed: false });
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

  function updatePreferenceDraft(settingPath: AllowedConfigPath, nextValue: ConfigValue) {
    setPendingDrafts((currentDrafts) => ({
      ...currentDrafts,
      [settingPath]: nextValue,
    }));
    setSaveState({ status: "idle" });
  }

  function openLiveModeConfirmation(
    source: "advanced" | "preference",
    setting: SettingDefinition,
    currentSettingValue: unknown,
    nextValue: ConfigValue,
  ) {
    setSaveState({ status: "idle" });
    setLiveModeConfirmation({
      status: "open",
      confirmed: false,
      currentValue: currentSettingValue,
      nextValue,
      setting,
      source,
    });
  }

  async function savePreferenceSetting(setting: SettingDefinition, nextValue: ConfigValue): Promise<boolean> {
    const saved = await saveConfigPatch(setting.path, nextValue);
    if (!saved) {
      return false;
    }
    setPendingDrafts((currentDrafts) => {
      const nextDrafts = { ...currentDrafts };
      delete nextDrafts[setting.path];
      return nextDrafts;
    });
    return true;
  }

  async function onPreferenceSave(setting: SettingDefinition) {
    const currentSettingValue = valueAtPath(settings, setting.path);
    const nextValue = preferenceDraftValue(setting, settings, pendingDrafts);
    if (requiresLiveModeConfirmation(setting.path, currentSettingValue, nextValue)) {
      openLiveModeConfirmation("preference", setting, currentSettingValue, nextValue);
      return;
    }
    await savePreferenceSetting(setting, nextValue);
  }

  async function saveRecipientEmail() {
    const email = recipientEmailDraft.trim();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setSaveState({ status: "error", message: "Enter a valid notification email address." });
      return;
    }
    const currentRecipients = valueAtPath(settings, "notifications.recipients");
    const recipients = currentRecipients && typeof currentRecipients === "object" && !Array.isArray(currentRecipients)
      ? { ...(currentRecipients as Record<string, unknown>) }
      : {};
    const recipientKey = configRecipientKey(snapshot);
    recipients[recipientKey] = email;
    await saveConfigPatch("notifications.recipients", recipients);
  }

  async function confirmLiveModeSave() {
    if (liveModeConfirmation.status !== "open" || !liveModeConfirmation.confirmed) {
      return;
    }
    const saved =
      liveModeConfirmation.source === "preference"
        ? await savePreferenceSetting(liveModeConfirmation.setting, liveModeConfirmation.nextValue)
        : await saveConfigPatch(liveModeConfirmation.setting.path, liveModeConfirmation.nextValue);
    if (!saved) {
      return;
    }
    setLiveModeConfirmation({ status: "closed" });
  }

  function setLiveModeConfirmed(confirmed: boolean) {
    setLiveModeConfirmation((current) => {
      if (current.status !== "open") {
        return current;
      }
      return { ...current, confirmed };
    });
  }

  return (
    <section className="panel config-preferences-panel">
      <div className="panel-heading">
        <div>
          <p className="section-label">Settings</p>
          <h2>Trading Preferences</h2>
        </div>
        <span className="status ok">applies next loop</span>
      </div>
      {initialSnapshot ? (
        <div className="config-page-summary" aria-label="Current config state">
          <div>
            <SlidersHorizontal aria-hidden="true" size={18} />
            <span>Environment</span>
            <strong>{initialSnapshot.environment}</strong>
          </div>
          <div>
            <Clock aria-hidden="true" size={18} />
            <span>Version</span>
            <strong>{currentVersion || initialSnapshot.version}</strong>
          </div>
          <div>
            <DollarSign aria-hidden="true" size={18} />
            <span>Apply timing</span>
            <strong>Next loop</strong>
          </div>
          <div>
            <ShieldCheck aria-hidden="true" size={18} />
            <span>Saved for</span>
            <strong>{initialSnapshot.username || initialSnapshot.config_owner || "shared"}</strong>
          </div>
        </div>
      ) : null}
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <section className="trading-profile-card" aria-labelledby="active-stock-profile-title">
        <div className="trading-profile-copy">
          <p className="section-label">Stock trading profile</p>
          <h3 id="active-stock-profile-title">Active day trader</h3>
          <p>
            Applies the coordinated one-minute scan, stock signal, model, position risk, and same-day exit settings. It preserves the current live-trading gate and Alpaca account mode.
          </p>
        </div>
        <div className="trading-profile-actions">
          <span className={`status ${activeStockProfileApplied ? "ok" : "idle"}`}>
            {activeStockProfileApplied ? "applied" : "not applied"}
          </span>
          <button
            className={`button ${activeStockProfileApplied ? "" : "primary"}`.trim()}
            disabled={activeStockProfileApplied}
            onClick={() => setProfileConfirmation({ open: true, confirmed: false })}
            type="button"
          >
            <Bot aria-hidden="true" size={16} />
            {activeStockProfileApplied ? "Profile applied" : "Review and apply"}
          </button>
        </div>
      </section>
      <section className="common-settings" aria-labelledby="common-settings-title">
        <div className="common-settings-heading">
          <div>
            <p className="section-label">Common settings</p>
            <h3 id="common-settings-title">Rules used most</h3>
            <p>Confidence and spread apply to {selectedVenueLabel(selectedVenue)}. Each saved value applies on the next loop.</p>
          </div>
          <span className="status idle">{selectedVenueLabel(selectedVenue)}</span>
        </div>
        <div className="common-settings-list">
          {commonSettings.map((setting) => {
            const currentSettingValue = valueAtPath(settings, setting.path);
            const draftValue = preferenceDraftValue(setting, settings, pendingDrafts);
            return (
              <PreferenceRow
                compact
                currentValue={currentSettingValue}
                draftValue={draftValue}
                hasPendingChange={hasPendingPreferenceChange(setting, currentSettingValue, draftValue)}
                key={`common-${setting.path}`}
                onChange={(nextValue) => updatePreferenceDraft(setting.path, nextValue)}
                onSave={() => void onPreferenceSave(setting)}
                setting={setting}
              />
            );
          })}
          <div className="preference-row common-recipient-row compact">
            <div className="preference-copy">
              <div className="preference-title-row"><Bell aria-hidden="true" size={16} /><strong>Notification email</strong></div>
              <p>Receives live-trade alerts and scheduled summaries. Existing additional recipients are preserved.</p>
            </div>
            <div className="preference-control">
              <input aria-label="Notification email" className="preference-text-input" onChange={(event) => { setRecipientEmailDraft(event.target.value); setSaveState({ status: "idle" }); }} type="email" value={recipientEmailDraft} />
              <div className="preference-value-summary" aria-live="polite"><span>Current: {savedRecipientEmail || "Not set"}</span>{recipientEmailDraft.trim() !== savedRecipientEmail ? <strong>New: {recipientEmailDraft.trim() || "Not set"}</strong> : null}</div>
              <button className={`button preference-save-button ${recipientEmailDraft.trim() !== savedRecipientEmail ? "primary" : ""}`.trim()} disabled={!recipientEmailDraft.trim() || recipientEmailDraft.trim() === savedRecipientEmail} onClick={() => void saveRecipientEmail()} type="button"><Save aria-hidden="true" size={15} />Apply</button>
            </div>
          </div>
        </div>
      </section>
      <Disclosure title="Advanced settings and risk controls">
        <div className="advanced-settings-content">
          <nav className="config-preference-nav" aria-label="Advanced settings sections">
            {PREFERENCE_SECTIONS.map((section) => (
              <a href={`#${sectionId(section.title)}`} key={section.title}>{section.title}</a>
            ))}
          </nav>
          <div className="preference-section-list">
            {PREFERENCE_SECTIONS.map((section) => {
              const Icon = section.icon;
              return (
                <FormSection body={section.body} icon={<Icon aria-hidden="true" size={19} strokeWidth={2.2} />} id={sectionId(section.title)} key={section.title} title={section.title}>
                  <div className="preference-row-list">
                    {section.settings.map((setting) => {
                      const currentSettingValue = valueAtPath(settings, setting.path);
                      const draftValue = preferenceDraftValue(setting, settings, pendingDrafts);
                      return <PreferenceRow currentValue={currentSettingValue} draftValue={draftValue} hasPendingChange={hasPendingPreferenceChange(setting, currentSettingValue, draftValue)} key={setting.path} onChange={(nextValue) => updatePreferenceDraft(setting.path, nextValue)} onSave={() => void onPreferenceSave(setting)} setting={setting} />;
                    })}
                  </div>
                </FormSection>
              );
            })}
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
          <Save aria-hidden="true" size={15} />
          Save stock universe
        </button>
          </form>
        </div>
      </Disclosure>
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
            Current version
            <input
              readOnly
              value={currentVersion}
            />
          </label>
          <button className="button primary" type="submit">
            Save
          </button>
        </form>
      </Disclosure>
      <LiveModeConfirmationDialog
        confirmation={liveModeConfirmation}
        environment={initialSnapshot?.environment ?? process.env.NEXT_PUBLIC_APP_ENV ?? "local"}
        onConfirm={() => void confirmLiveModeSave()}
        onConfirmedChange={setLiveModeConfirmed}
        onOpenChange={(open) => {
          if (!open) {
            setLiveModeConfirmation({ status: "closed" });
          }
        }}
      />
      <ActiveTradingProfileDialog
        accountMode={alpacaAccountMode}
        confirmation={profileConfirmation}
        environment={initialSnapshot?.environment ?? process.env.NEXT_PUBLIC_APP_ENV ?? "local"}
        liveTradingOn={liveTradingOn}
        onConfirm={() => void applyActiveStockProfile()}
        onConfirmedChange={(confirmed) =>
          setProfileConfirmation((current) => ({ ...current, confirmed }))
        }
        onOpenChange={(open) => setProfileConfirmation({ open, confirmed: false })}
      />
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

function ActiveTradingProfileDialog({
  accountMode,
  confirmation,
  environment,
  liveTradingOn,
  onConfirm,
  onConfirmedChange,
  onOpenChange,
}: {
  accountMode: string;
  confirmation: TradingProfileConfirmationState;
  environment: string;
  liveTradingOn: boolean;
  onConfirm: () => void;
  onConfirmedChange: (confirmed: boolean) => void;
  onOpenChange: (open: boolean) => void;
}) {
  if (!confirmation.open) {
    return null;
  }
  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" aria-describedby="active-profile-confirmation-body">
          <div className="dialog-heading">
            <AlertTriangle aria-hidden="true" size={22} strokeWidth={2.4} />
            <div>
              <Dialog.Title>Apply active stock day trader</Dialog.Title>
              <Dialog.Description id="active-profile-confirmation-body">
                This saves one audited config version for {environment} and applies it on the next trading loop.
              </Dialog.Description>
            </div>
          </div>
          <div className="setting-help-summary">
            <div>
              <span>Live trading</span>
              <strong>{liveTradingOn ? "On, unchanged" : "Off, unchanged"}</strong>
            </div>
            <div>
              <span>Alpaca account</span>
              <strong>{accountMode}, unchanged</strong>
            </div>
            <div>
              <span>Schedule</span>
              <strong>Every 60 seconds</strong>
            </div>
          </div>
          <div className="setting-help-body profile-confirmation-body">
            <section>
              <h3>Entry and model settings</h3>
              <p>54% confidence, 1.5% edge, four top candidates per provider per run, all six stock scanners, and rolling 24-hour model budgets.</p>
            </section>
            <section>
              <h3>Position controls</h3>
              <p>$100 maximum order, $100 daily loss limit, five open positions, 10% allocation per symbol, and a 0.5% estimated slippage limit.</p>
            </section>
            <section>
              <h3>Exit controls</h3>
              <p>2% profit target, 1% stop loss, 1% trailing stop, six-hour maximum hold, regular-hours trading, and closing 15 minutes before the regular market close.</p>
            </section>
            {liveTradingOn && accountMode === "live" ? (
              <p className="profile-live-warning" role="alert">
                The current account is live. Approved signals may submit real-money orders beginning with the next loop after this save.
              </p>
            ) : null}
          </div>
          <label className="checkbox-row">
            <input
              checked={confirmation.confirmed}
              type="checkbox"
              onChange={(event) => onConfirmedChange(event.target.checked)}
            />
            <span>
              I reviewed the stock entry, risk, and exit settings and understand they apply on the next loop.
            </span>
          </label>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button className="button" type="button">
                <X aria-hidden="true" size={15} />
                Cancel
              </button>
            </Dialog.Close>
            <button
              className={liveTradingOn && accountMode === "live" ? "button danger" : "button primary"}
              disabled={!confirmation.confirmed}
              onClick={onConfirm}
              type="button"
            >
              Apply profile
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function LiveModeConfirmationDialog({
  confirmation,
  environment,
  onConfirm,
  onConfirmedChange,
  onOpenChange,
}: {
  confirmation: LiveModeConfirmationState;
  environment: string;
  onConfirm: () => void;
  onConfirmedChange: (confirmed: boolean) => void;
  onOpenChange: (open: boolean) => void;
}) {
  if (confirmation.status !== "open") {
    return null;
  }
  const currentValue = formatPreferenceDisplay(confirmation.setting, confirmation.currentValue);
  const nextValue = formatPreferenceDisplay(confirmation.setting, confirmation.nextValue);
  const enablingLive = Boolean(confirmation.nextValue);

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" aria-describedby="live-mode-confirmation-body">
          <div className="dialog-heading">
            <AlertTriangle aria-hidden="true" size={22} strokeWidth={2.4} />
            <div>
              <Dialog.Title>{enablingLive ? "Confirm live mode" : "Confirm live mode change"}</Dialog.Title>
              <Dialog.Description id="live-mode-confirmation-body">
                This changes the live trading gate for {environment}. It applies on the next loop after the config save.
              </Dialog.Description>
            </div>
          </div>
          <div className="setting-help-summary">
            <div>
              <span>Current value</span>
              <strong>{currentValue}</strong>
            </div>
            <div>
              <span>Requested value</span>
              <strong>{nextValue}</strong>
            </div>
            <div>
              <span>Scope</span>
              <strong>{environment}</strong>
            </div>
          </div>
          <div className="setting-help-body">
            <section>
              <h3>Before saving</h3>
              <p>
                Confirm account readiness, venue flags, risk limits, notifications, open orders,
                and emergency-stop state before changing this gate.
              </p>
            </section>
          </div>
          <label className="checkbox-row">
            <input
              checked={confirmation.confirmed}
              type="checkbox"
              onChange={(event) => onConfirmedChange(event.target.checked)}
            />
            <span>
              I understand this changes whether approved orders can reach a live trading account.
            </span>
          </label>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button className="button" type="button">
                <X aria-hidden="true" size={15} />
                Cancel
              </button>
            </Dialog.Close>
            <button
              className={enablingLive ? "button danger" : "button primary"}
              disabled={!confirmation.confirmed}
              onClick={onConfirm}
              type="button"
            >
              {enablingLive ? "Save live mode" : "Save live mode change"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PreferenceRow({
  compact = false,
  currentValue,
  draftValue,
  hasPendingChange,
  onChange,
  onSave,
  setting,
}: {
  compact?: boolean;
  currentValue: unknown;
  draftValue: ConfigValue;
  hasPendingChange: boolean;
  onChange: (value: ConfigValue) => void;
  onSave: () => void;
  setting: SettingDefinition;
}) {
  const detail = CONFIG_PATH_DETAILS[setting.path];
  const inputId = sectionId(`setting-${setting.path}`);
  const descriptionId = `${inputId}-description`;
  const terms = termsForSetting(setting, detail);

  return (
    <div className={`preference-row ${compact ? "compact" : ""}`.trim()}>
      <div className="preference-copy">
        <div className="preference-title-row">
          <label htmlFor={inputId}>{detail.label}</label>
          {!compact ? <span className="preference-stage">{setting.stage}</span> : null}
          {!compact ? (
            <SettingHelpDialog
              currentValue={formatPreferenceDisplay(setting, currentValue)}
              detail={detail}
              path={setting.path}
              setting={setting}
              terms={terms}
            />
          ) : null}
        </div>
        <p id={descriptionId}>{detail.description}</p>
        {setting.note ? <p className="preference-note">{setting.note}</p> : null}
        {!compact ? <small>{detail.effect}</small> : null}
        {!compact ? <code>{setting.path}</code> : null}
      </div>
      <div className="preference-control">
        {renderPreferenceControl(setting, inputId, descriptionId, draftValue, onChange)}
        <div className="preference-value-summary" aria-live="polite">
          <span>Current: {formatPreferenceDisplay(setting, currentValue)}</span>
          {hasPendingChange ? <strong>New: {formatPreferenceDisplay(setting, draftValue)}</strong> : null}
        </div>
        <button
          className={`button preference-save-button ${hasPendingChange ? "primary" : ""}`.trim()}
          disabled={!hasPendingChange}
          onClick={onSave}
          type="button"
        >
          <Save aria-hidden="true" size={15} />
          Apply
        </button>
      </div>
    </div>
  );
}

function SettingHelpDialog({
  currentValue,
  detail,
  path,
  setting,
  terms,
}: {
  currentValue: string;
  detail: (typeof CONFIG_PATH_DETAILS)[AllowedConfigPath];
  path: AllowedConfigPath;
  setting: SettingDefinition;
  terms: GlossaryTerm[];
}) {
  const descriptionId = `${sectionId(`setting-help-${path}`)}-description`;

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          aria-label={`Explain ${detail.label}`}
          className="icon-button preference-help-button"
          type="button"
        >
          <CircleHelp aria-hidden="true" size={15} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content setting-help-dialog" aria-describedby={descriptionId}>
          <div className="dialog-heading">
            <CircleHelp aria-hidden="true" size={22} strokeWidth={2.4} />
            <div>
              <Dialog.Title>{detail.label}</Dialog.Title>
              <Dialog.Description id={descriptionId}>{detail.description}</Dialog.Description>
            </div>
          </div>
          <div className="setting-help-summary">
            <div>
              <span>Stage</span>
              <strong>{setting.stage}</strong>
            </div>
            <div>
              <span>Current value</span>
              <strong>{currentValue}</strong>
            </div>
            <div>
              <span>Applies</span>
              <strong>Next loop</strong>
            </div>
          </div>
          <div className="setting-help-body">
            <section>
              <h3>What this changes</h3>
              <p>{detail.effect}</p>
              {setting.note ? <p>{setting.note}</p> : null}
            </section>
            <section>
              <h3>Terms in this setting</h3>
              <dl className="setting-term-list">
                {terms.map((term) => (
                  <div key={term.term}>
                    <dt>{term.term}</dt>
                    <dd>{term.definition}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section>
              <h3>System path</h3>
              <p>
                Stored as <code>{path}</code> in your active database config version for this environment.
              </p>
            </section>
          </div>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button className="button" type="button">
                <X aria-hidden="true" size={15} />
                Close
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function termsForSetting(
  setting: SettingDefinition,
  detail: (typeof CONFIG_PATH_DETAILS)[AllowedConfigPath],
): GlossaryTerm[] {
  const source = [
    detail.label,
    detail.description,
    detail.effect,
    detail.valueHint,
    setting.stage,
    setting.note,
    setting.path,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const matched = CONFIG_GLOSSARY.filter((entry) =>
    entry.matches.some((match) => source.includes(match.toLowerCase())),
  ).map(({ term, definition }) => ({ term, definition }));
  if (matched.length) {
    return matched;
  }
  return [
    {
      term: "Setting",
      definition:
        "A saved runtime value used by the app when it starts the next loop. It is stored for your user in this environment, not just this browser session.",
    },
  ];
}

function renderPreferenceControl(
  setting: SettingDefinition,
  inputId: string,
  descriptionId: string,
  value: ConfigValue,
  onChange: (value: ConfigValue) => void,
) {
  if (setting.kind === "switch") {
    const checked = Boolean(value);
    return (
      <label className="preference-switch-control" htmlFor={inputId}>
        <input
          aria-describedby={descriptionId}
          checked={checked}
          id={inputId}
          onChange={(event) => onChange(event.target.checked)}
          type="checkbox"
        />
        <span className="preference-switch-track" aria-hidden="true">
          <span />
        </span>
        <strong>{checked ? "On" : "Off"}</strong>
      </label>
    );
  }

  if (setting.kind === "select") {
    return (
      <select
        aria-describedby={descriptionId}
        className="preference-select"
        id={inputId}
        value={String(value)}
        onChange={(event) => onChange(event.target.value)}
      >
        {setting.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (setting.kind === "text") {
    return (
      <input
        aria-describedby={descriptionId}
        className="preference-text-input"
        id={inputId}
        type="text"
        value={String(value)}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  if (setting.kind === "range") {
    const displayValue = displayNumberForSetting(setting, value);
    const clampedDisplayValue = clamp(displayValue, setting.min, setting.max);
    return (
      <div className="preference-range-control">
        <input
          aria-describedby={`${descriptionId} ${inputId}-range`}
          id={inputId}
          max={setting.max}
          min={setting.min}
          onChange={(event) => onChange(configNumberFromDisplay(setting, event.target.valueAsNumber))}
          step={setting.step}
          type="range"
          value={clampedDisplayValue}
        />
        <label className="preference-number-field" htmlFor={`${inputId}-number`}>
          <span id={`${inputId}-range`}>{formatUnitLabel(setting.unit)}</span>
          <input
            aria-describedby={descriptionId}
            aria-label={`${CONFIG_PATH_DETAILS[setting.path].label} value`}
            id={`${inputId}-number`}
            max={setting.max}
            min={setting.min}
            onChange={(event) => onChange(configNumberFromDisplay(setting, event.target.valueAsNumber))}
            step={setting.step}
            type="number"
            value={trimNumber(displayValue)}
          />
        </label>
      </div>
    );
  }

  const displayValue = displayNumberForSetting(setting, value);
  return (
    <label className="preference-number-field preference-number-only" htmlFor={inputId}>
      <span>{formatUnitLabel(setting.unit)}</span>
      <input
        aria-describedby={descriptionId}
        id={inputId}
        min={setting.min}
        onChange={(event) => onChange(configNumberFromDisplay(setting, event.target.valueAsNumber))}
        step={setting.step ?? 1}
        type="number"
        value={trimNumber(displayValue)}
      />
    </label>
  );
}

function settingForPath(path: AllowedConfigPath): SettingDefinition | null {
  for (const section of PREFERENCE_SECTIONS) {
    const setting = section.settings.find((item) => item.path === path);
    if (setting) {
      return setting;
    }
  }
  return null;
}

function commonSettingsForVenue(venue: string): SettingDefinition[] {
  const alpaca = venue === "alpaca";
  const paths: AllowedConfigPath[] = [
    alpaca ? "reasoning.alpaca.min_confidence" : "reasoning.polymarket.min_confidence",
    alpaca ? "scanner.alpaca.max_spread" : "scanner.polymarket.max_spread",
    "live_enabled",
    "notifications.email_on_trade_placed",
    "venues.polymarket_us.enabled",
    "venues.polymarket_international.enabled",
    "venues.alpaca.enabled",
  ];
  return paths.map(settingForPath).filter((setting): setting is SettingDefinition => setting !== null);
}

function configRecipientKey(snapshot: ConfigSnapshot): string {
  return snapshot.username?.trim() || snapshot.config_owner?.trim() || "operator";
}

function recipientEmailForOwner(value: unknown, snapshot?: ConfigSnapshot): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const recipient = snapshot
    ? (value as Record<string, unknown>)[configRecipientKey(snapshot)]
    : undefined;
  return typeof recipient === "string" ? recipient : "";
}

function selectedVenueLabel(value: string): string {
  return VENUE_OPTIONS.find((option) => option.value === value)?.label ?? "Polymarket US";
}

function requiresLiveModeConfirmation(
  path: AllowedConfigPath,
  currentValue: unknown,
  nextValue: ConfigValue,
): boolean {
  return path === "live_enabled" && Boolean(currentValue) !== Boolean(nextValue);
}

function preferenceDraftValue(
  setting: SettingDefinition,
  settings: Record<string, unknown> | undefined,
  pendingDrafts: Partial<Record<AllowedConfigPath, ConfigValue>>,
): ConfigValue {
  const pending = pendingDrafts[setting.path];
  if (pending !== undefined) {
    return pending;
  }
  return normalizedPreferenceValue(setting, valueAtPath(settings, setting.path));
}

function normalizedPreferenceValue(setting: SettingDefinition, value: unknown): ConfigValue {
  if (setting.kind === "switch") {
    return typeof value === "boolean" ? value : (setting.fallback ?? false);
  }
  if (setting.kind === "select") {
    const stringValue = typeof value === "string" ? value : setting.fallback;
    return setting.options.some((option) => option.value === stringValue) ? stringValue : setting.fallback;
  }
  if (setting.kind === "text") {
    return typeof value === "string" ? value : setting.fallback;
  }
  const parsed = Number(value);
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  return configNumberFromDisplay(setting, setting.fallback);
}

function hasPendingPreferenceChange(
  setting: SettingDefinition,
  currentValue: unknown,
  draftValue: ConfigValue,
): boolean {
  return !configValuesEqual(normalizedPreferenceValue(setting, currentValue), draftValue);
}

function displayNumberForSetting(
  setting: Extract<SettingDefinition, { kind: "number" | "range" }>,
  value: ConfigValue,
): number {
  const parsed = Number(value);
  const fallback = configNumberFromDisplay(setting, setting.fallback);
  const configValue = Number.isFinite(parsed) ? parsed : fallback;
  return configValue * (setting.displayMultiplier ?? 1);
}

function configNumberFromDisplay(
  setting: Extract<SettingDefinition, { kind: "number" | "range" }>,
  displayValue: number,
): number {
  const fallback = setting.fallback;
  const parsed = Number.isFinite(displayValue) ? displayValue : fallback;
  return parsed / (setting.displayMultiplier ?? 1);
}

function formatPreferenceDisplay(setting: SettingDefinition, value: unknown): string {
  const normalized = normalizedPreferenceValue(setting, value);
  if (setting.kind === "switch") {
    return normalized ? "On" : "Off";
  }
  if (setting.kind === "select") {
    return setting.options.find((option) => option.value === normalized)?.label ?? String(normalized);
  }
  if (setting.kind === "text") {
    return String(normalized || "not set");
  }
  const displayValue = displayNumberForSetting(setting, normalized);
  if (setting.unit === "usd") {
    return formatUsd(displayValue);
  }
  if (setting.unit === "percent") {
    return `${trimNumber(displayValue)}%`;
  }
  if (setting.unit === "seconds") {
    return formatDurationSeconds(displayValue);
  }
  if (setting.unit === "minutes") {
    return `${trimNumber(displayValue)} min`;
  }
  if (setting.unit === "hours") {
    return `${trimNumber(displayValue)} hr`;
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(displayValue);
}

function formatUnitLabel(unit: SettingUnit): string {
  if (unit === "usd") {
    return "USD";
  }
  if (unit === "percent") {
    return "%";
  }
  if (unit === "seconds") {
    return "sec";
  }
  if (unit === "minutes") {
    return "min";
  }
  if (unit === "hours") {
    return "hr";
  }
  return "count";
}

function configValuesEqual(left: ConfigValue, right: ConfigValue): boolean {
  if (typeof left === "number" && typeof right === "number") {
    return Math.abs(left - right) < 0.0000001;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: Math.abs(value) < 1 ? 4 : 2,
    style: "currency",
  }).format(value);
}

function formatDurationSeconds(value: number): string {
  if (value >= 3600 && value % 3600 === 0) {
    return `${trimNumber(value / 3600)} hr`;
  }
  if (value >= 60 && value % 60 === 0) {
    return `${trimNumber(value / 60)} min`;
  }
  return `${trimNumber(value)} sec`;
}

function trimNumber(value: number): string {
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function sectionId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
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

function activeStockProfileIsApplied(settings: Record<string, unknown> | undefined): boolean {
  const expected: Record<string, string | number | boolean> = {
    trading_profile: ACTIVE_STOCK_PROFILE,
    default_selected_venue: "alpaca",
    "venues.alpaca.enabled": true,
    trading_loop_interval_seconds: 900,
    "scanner.alpaca.min_quote_liquidity": 0.5,
    "scanner.alpaca.max_spread": 1,
    "scanner.alpaca.min_history_bars": 2,
    "scanner.alpaca.strategies.momentum.enabled": true,
    "scanner.alpaca.strategies.momentum.min_change_pct": 0.005,
    "scanner.alpaca.strategies.mean_reversion.enabled": true,
    "scanner.alpaca.strategies.mean_reversion.min_deviation_pct": 0.01,
    "scanner.alpaca.strategies.gap.enabled": true,
    "scanner.alpaca.strategies.gap.min_gap_pct": 0.01,
    "scanner.alpaca.strategies.liquidity.enabled": true,
    "scanner.alpaca.strategies.liquidity.min_volume": 100000,
    "scanner.alpaca.strategies.volatility.enabled": true,
    "scanner.alpaca.strategies.volatility.min_range_pct": 0.015,
    "scanner.alpaca.strategies.unusual_volume.enabled": true,
    "scanner.alpaca.strategies.unusual_volume.min_ratio": 1.25,
    "reasoning.max_prompts_per_provider_per_run": 4,
    "reasoning.alpaca.min_confidence": 0.54,
    "reasoning.alpaca.min_edge": 0.015,
    "llm.openai.budget_usd": 20,
    "llm.openai.settings.budget_window_hours": 24,
    "llm.claude.budget_usd": 20,
    "llm.claude.settings.budget_window_hours": 24,
    "risk.alpaca.max_position_usd": 100,
    "risk.alpaca.max_daily_loss_usd": 100,
    "risk.alpaca.max_open_positions": 5,
    "risk.alpaca.max_portfolio_allocation_per_symbol": 0.1,
    "risk.alpaca.market_order_slippage_threshold": 0.005,
    "exit.alpaca.profit_target_pct": 0.02,
    "exit.alpaca.stop_loss_pct": 0.01,
    "exit.alpaca.trailing_stop_pct": 0.01,
    "exit.alpaca.max_position_age_hours": 6,
    "exit.alpaca.min_stale_price_move_pct": 0.005,
    "exit.alpaca.market_hours_only": true,
    "exit.alpaca.close_before_market_close_minutes": 15,
  };
  return Object.entries(expected).every(([path, expectedValue]) => {
    const currentValue = valueAtPath(settings, path);
    if (typeof expectedValue === "number") {
      return Number(currentValue) === expectedValue;
    }
    return currentValue === expectedValue;
  });
}

function parseCurrentVersion(message: string): string | null {
  try {
    const payload = JSON.parse(message) as { current_version?: string };
    return payload.current_version ?? null;
  } catch {
    return null;
  }
}

function valueAtPath(settings: Record<string, unknown> | undefined, path: string): unknown {
  if (!settings) {
    return undefined;
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
