import "server-only";

// REQ: REQ-OBS-001, REQ-OBS-002

const DEFAULT_FRONTEND_SERVICE_NAME = "codex-poly-bot-frontend";
const SIGNOZ_CLOUD_ENDPOINT_TEMPLATE = "https://ingest.{region}.signoz.cloud:443";

export type SignozSignal = "traces" | "logs";

export type FrontendTelemetryConfig = {
  enabled: boolean;
  serviceName: string;
  serviceVersion: string;
  environment: string;
  tracesEndpoint: string;
  logsEndpoint: string;
};

type ServerSignozConfig = {
  enabled: boolean;
  endpoint: string;
  tracesEndpoint: string;
  logsEndpoint: string;
  headers: Record<string, string>;
};

export function frontendTelemetryConfig(): FrontendTelemetryConfig {
  const serverConfig = serverSignozConfig();
  const frontendEnabled = boolEnv("SIGNOZ_FRONTEND_ENABLED", false);
  return {
    enabled: frontendEnabled && serverConfig.enabled,
    serviceName: process.env.SIGNOZ_FRONTEND_SERVICE_NAME || DEFAULT_FRONTEND_SERVICE_NAME,
    serviceVersion: process.env.APP_VERSION || "0.1.0",
    environment: process.env.NEXT_PUBLIC_APP_ENV || process.env.APP_ENV || process.env.ENVIRONMENT || "local",
    tracesEndpoint: "/api/observability/v1/traces",
    logsEndpoint: "/api/observability/v1/logs",
  };
}

export function signozSignalEndpoint(signal: SignozSignal): string {
  const config = serverSignozConfig();
  return signal === "traces" ? config.tracesEndpoint : config.logsEndpoint;
}

export function signozHeaders(): Record<string, string> {
  return serverSignozConfig().headers;
}

export function signozTelemetryEnabled(): boolean {
  return serverSignozConfig().enabled;
}

export function isTrustedTelemetryOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) {
    return process.env.NODE_ENV !== "production" || process.env.APP_ENV === "local";
  }
  const url = new URL(request.url);
  const trustedOrigins = new Set<string>([url.origin]);
  for (const configured of [
    process.env.NEXTAUTH_URL,
    process.env.DASHBOARD_TRUSTED_ORIGINS,
  ]) {
    for (const value of (configured ?? "").split(",")) {
      const trimmed = value.trim();
      if (trimmed) {
        trustedOrigins.add(trimmed);
      }
    }
  }
  return trustedOrigins.has(origin);
}

function serverSignozConfig(): ServerSignozConfig {
  const region = process.env.SIGNOZ_REGION?.trim() ?? "";
  const endpoint = baseEndpoint(region);
  const headers = otlpHeaders();
  const enabled = boolEnv("SIGNOZ_ENABLED", Boolean(endpoint));
  const disabled = boolEnv("OTEL_SDK_DISABLED", false);
  return {
    enabled: enabled && !disabled && Boolean(endpoint),
    endpoint,
    tracesEndpoint: process.env.SIGNOZ_OTLP_TRACES_ENDPOINT?.trim() || signalEndpoint(endpoint, "traces"),
    logsEndpoint: process.env.SIGNOZ_OTLP_LOGS_ENDPOINT?.trim() || signalEndpoint(endpoint, "logs"),
    headers,
  };
}

function baseEndpoint(region: string): string {
  const configured = process.env.SIGNOZ_OTLP_ENDPOINT || process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  if (configured?.trim()) {
    return configured.trim().replace(/\/$/, "");
  }
  if (region) {
    return SIGNOZ_CLOUD_ENDPOINT_TEMPLATE.replace("{region}", region);
  }
  return "";
}

function signalEndpoint(endpoint: string, signal: SignozSignal): string {
  if (!endpoint) {
    return "";
  }
  if (endpoint.endsWith(`/v1/${signal}`)) {
    return endpoint;
  }
  return `${endpoint.replace(/\/$/, "")}/v1/${signal}`;
}

function otlpHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const item of (process.env.OTEL_EXPORTER_OTLP_HEADERS ?? "").split(",")) {
    const [key, ...valueParts] = item.split("=");
    if (key?.trim() && valueParts.length > 0) {
      headers[key.trim()] = valueParts.join("=").trim();
    }
  }
  const ingestionKey = process.env.SIGNOZ_INGESTION_KEY?.trim();
  if (ingestionKey) {
    headers["signoz-ingestion-key"] = ingestionKey;
  }
  return headers;
}

function boolEnv(name: string, defaultValue: boolean): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return defaultValue;
  }
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}
