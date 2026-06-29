"use client";

import { useEffect, useRef, useState } from "react";

import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import type { LoopObservabilityView } from "@/components/dashboard/loop-monitor";

// REQ: REQ-UI-004, REQ-UI-008, REQ-OBS-005

export type TickScheduleView = {
  environment: string;
  generatedAt: string;
  intervalSeconds: number;
  lastTickAt?: string | null;
  lastTickStatus?: string | null;
  lastTickRunId?: string | null;
  lastTickSource?: string | null;
  lastHeartbeatAt?: string | null;
  heartbeatStatus?: string | null;
  ageSeconds?: number | null;
  nextTickAt: string;
  secondsUntilNextTick: number;
  due: boolean;
  source?: string | null;
};

export type DashboardRealtimeSnapshot = {
  environment: string;
  generatedAt: string;
  operations: OperationsSummaryView;
  marketData: MarketDataPullView;
  tickSchedule: TickScheduleView;
  loop?: LoopObservabilityView;
};

type RealtimeStatus = "connecting" | "connected" | "polling" | "offline";

export function useDashboardRealtime({
  onSnapshot,
  enabled = true,
}: {
  onSnapshot: (snapshot: DashboardRealtimeSnapshot) => void;
  enabled?: boolean;
}) {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const [message, setMessage] = useState("Connecting to realtime updates.");
  const onSnapshotRef = useRef(onSnapshot);

  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let closed = false;
    let socket: WebSocket | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    async function connect() {
      setStatus("connecting");
      setMessage("Connecting to realtime updates.");
      try {
        const response = await fetch("/api/dashboard/realtime-token", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`token request failed with status ${response.status}`);
        }
        const tokenPayload = (await response.json()) as {
          token: string;
          environment: string;
          websocketUrl: string;
        };
        if (closed) {
          return;
        }
        const url = new URL(tokenPayload.websocketUrl);
        url.searchParams.set("token", tokenPayload.token);
        url.searchParams.set("environment", tokenPayload.environment);
        socket = new WebSocket(url.toString());
        socket.onopen = () => {
          if (closed) {
            return;
          }
          setStatus("connected");
          setMessage("Realtime updates connected.");
        };
        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(String(event.data)) as {
              type?: string;
              data?: DashboardRealtimeSnapshot;
            };
            if (payload.type === "dashboard_snapshot" && payload.data) {
              onSnapshotRef.current(payload.data);
            }
          } catch {
            setMessage("Realtime update was not valid JSON.");
          }
        };
        socket.onerror = () => {
          setMessage("Realtime socket error. Using polling if the socket closes.");
        };
        socket.onclose = () => {
          if (!closed) {
            startPolling();
          }
        };
      } catch (error) {
        if (!closed) {
          setMessage(error instanceof Error ? error.message : "Realtime connection failed.");
          startPolling();
        }
      }
    }

    function startPolling() {
      if (pollTimer || closed) {
        return;
      }
      setStatus("polling");
      setMessage("Realtime socket unavailable. Polling dashboard snapshots.");
      void pollSnapshot();
      pollTimer = setInterval(() => void pollSnapshot(), 10000);
    }

    async function pollSnapshot() {
      try {
        const response = await fetch("/dashboard-api/dashboard/realtime-snapshot", {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`snapshot request failed with status ${response.status}`);
        }
        onSnapshotRef.current((await response.json()) as DashboardRealtimeSnapshot);
      } catch (error) {
        setStatus("offline");
        setMessage(error instanceof Error ? error.message : "Realtime polling failed.");
      }
    }

    void connect();

    return () => {
      closed = true;
      if (pollTimer) {
        clearInterval(pollTimer);
      }
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close(1000, "component unmounted");
      }
    };
  }, [enabled]);

  return { status, message };
}
