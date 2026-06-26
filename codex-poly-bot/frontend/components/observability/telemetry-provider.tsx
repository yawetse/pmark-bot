"use client";

import { useEffect } from "react";

// REQ: REQ-OBS-001, REQ-OBS-002

export function TelemetryProvider() {
  useEffect(() => {
    void import("@/lib/observability/browser-otel").then(({ initializeBrowserTelemetry }) => {
      void initializeBrowserTelemetry();
    });
  }, []);

  return null;
}
