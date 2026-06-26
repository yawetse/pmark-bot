"use client";

import { logs, SeverityNumber, type AnyValueMap } from "@opentelemetry/api-logs";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { OTLPLogExporter } from "@opentelemetry/exporter-logs-otlp-http";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  BatchLogRecordProcessor,
  LoggerProvider,
} from "@opentelemetry/sdk-logs";
import {
  BatchSpanProcessor,
  WebTracerProvider,
} from "@opentelemetry/sdk-trace-web";

// REQ: REQ-OBS-001, REQ-OBS-002

type TelemetryConfig = {
  enabled: boolean;
  serviceName: string;
  serviceVersion: string;
  environment: string;
  tracesEndpoint: string;
  logsEndpoint: string;
};

declare global {
  interface Window {
    __codexPolyBotTelemetryInitialized?: boolean;
    __codexPolyBotConsoleErrorWrapped?: boolean;
  }
}

export async function initializeBrowserTelemetry(): Promise<void> {
  if (typeof window === "undefined" || window.__codexPolyBotTelemetryInitialized) {
    return;
  }
  window.__codexPolyBotTelemetryInitialized = true;

  const config = await loadTelemetryConfig();
  if (!config?.enabled) {
    return;
  }

  const resource = resourceFromAttributes({
    "service.name": config.serviceName,
    "service.version": config.serviceVersion,
    "deployment.environment": config.environment,
    "service.namespace": "codex-poly-bot",
  });

  const traceExporter = new OTLPTraceExporter({
    url: config.tracesEndpoint,
  });
  const tracerProvider = new WebTracerProvider({
    resource,
    spanProcessors: [new BatchSpanProcessor(traceExporter)],
  });
  tracerProvider.register({
    contextManager: new ZoneContextManager(),
  });

  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        ignoreUrls: [/\/api\/observability\/v1\//],
        propagateTraceHeaderCorsUrls: [/.*/],
      }),
    ],
  });

  const loggerProvider = new LoggerProvider({
    resource,
    processors: [
      new BatchLogRecordProcessor(
        new OTLPLogExporter({
          url: config.logsEndpoint,
        }),
      ),
    ],
  });
  logs.setGlobalLoggerProvider(loggerProvider);
  registerBrowserErrorCapture();
  emitFrontendLog("frontend.telemetry.initialized", SeverityNumber.INFO, {
    environment: config.environment,
  });
}

export function emitFrontendLog(
  body: string,
  severityNumber: SeverityNumber = SeverityNumber.INFO,
  attributes: AnyValueMap = {},
): void {
  logs.getLogger("codex-poly-bot-frontend").emit({
    body,
    severityNumber,
    severityText: SeverityNumber[severityNumber] ?? "INFO",
    attributes,
  });
}

async function loadTelemetryConfig(): Promise<TelemetryConfig | null> {
  try {
    const response = await fetch("/api/observability/config", {
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as TelemetryConfig;
  } catch {
    return null;
  }
}

function registerBrowserErrorCapture(): void {
  window.addEventListener("error", (event) => {
    emitFrontendLog("window.error", SeverityNumber.ERROR, {
      "exception.message": event.message,
      "exception.type": event.error?.name || "Error",
      "exception.stacktrace": event.error?.stack || "",
      "exception.source": event.filename,
      "exception.lineno": event.lineno,
      "exception.colno": event.colno,
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    emitFrontendLog("window.unhandledrejection", SeverityNumber.ERROR, {
      "exception.message": errorMessage(reason),
      "exception.type": reason?.name || typeof reason || "UnhandledRejection",
      "exception.stacktrace": reason?.stack || "",
    });
  });

  if (window.__codexPolyBotConsoleErrorWrapped) {
    return;
  }
  window.__codexPolyBotConsoleErrorWrapped = true;
  const originalConsoleError = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    emitFrontendLog("console.error", SeverityNumber.ERROR, {
      "exception.message": args.map(errorMessage).join(" "),
      "exception.type": "ConsoleError",
      "exception.stacktrace": new Error().stack || "",
    });
    originalConsoleError(...args);
  };
}

function errorMessage(value: unknown): string {
  if (value instanceof Error) {
    return value.message;
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
