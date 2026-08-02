"use client";

import { useEffect, useRef, useState } from "react";

import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import type { LoopObservabilityView } from "@/components/dashboard/loop-monitor";
import type { VenuePortfolioView } from "@/components/dashboard/venue-portfolio-panel";

// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-014, REQ-UI-015, REQ-OBS-005

const POLL_INTERVAL_MS = 10_000;
const MAX_POLL_DELAY_MS = 60_000;
const SOCKET_RECONNECT_INTERVAL_MS = 5_000;
const MAX_SOCKET_RECONNECT_DELAY_MS = 60_000;

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
  portfolio?: VenuePortfolioView;
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
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pollAbortController: AbortController | null = null;
    let pollingStarted = false;
    let pollFailureCount = 0;
    let socketFailureCount = 0;
    let connecting = false;

    async function connect() {
      if (
        closed ||
        connecting ||
        (socket !== null && socket.readyState <= WebSocket.OPEN)
      ) {
        return;
      }
      connecting = true;
      if (!pollingStarted) {
        setStatus("connecting");
        setMessage("Connecting to realtime updates.");
      }
      try {
        const response = await fetch("/dashboard-realtime-token", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`token request failed with status ${response.status}`);
        }
        const tokenPayload = (await response.json()) as {
          token: string;
          environment: string;
          websocketUrl: string;
        };
        if (closed) {
          connecting = false;
          return;
        }
        const url = new URL(tokenPayload.websocketUrl);
        url.searchParams.set("token", tokenPayload.token);
        url.searchParams.set("environment", tokenPayload.environment);
        const nextSocket = new WebSocket(url.toString());
        socket = nextSocket;
        nextSocket.onopen = () => {
          if (closed) {
            nextSocket.close(1000, "component unmounted");
            return;
          }
          connecting = false;
          socketFailureCount = 0;
          stopPolling();
          setStatus("connected");
          setMessage("Realtime updates connected.");
        };
        nextSocket.onmessage = (event) => {
          try {
            const payload = JSON.parse(String(event.data)) as {
              type?: string;
              data?: DashboardRealtimeSnapshot;
            };
            if (payload.type === "dashboard_snapshot" && payload.data) {
              onSnapshotRef.current(payload.data);
            } else if (payload.type === "heartbeat") {
              setStatus("connected");
              setMessage("Realtime updates connected.");
            }
          } catch {
            setMessage("Realtime update was not valid JSON.");
          }
        };
        nextSocket.onerror = () => {
          setMessage("Realtime socket error. Using polling if the socket closes.");
        };
        nextSocket.onclose = () => {
          if (socket === nextSocket) {
            socket = null;
          }
          connecting = false;
          if (!closed) {
            socketFailureCount += 1;
            startPolling();
            scheduleReconnect();
          }
        };
      } catch (error) {
        connecting = false;
        if (!closed) {
          socketFailureCount += 1;
          setMessage(error instanceof Error ? error.message : "Realtime connection failed.");
          startPolling();
          scheduleReconnect();
        }
      }
    }

    function scheduleReconnect() {
      if (closed || reconnectTimer) {
        return;
      }
      const delay = Math.min(
        SOCKET_RECONNECT_INTERVAL_MS * 2 ** Math.max(0, socketFailureCount - 1),
        MAX_SOCKET_RECONNECT_DELAY_MS,
      );
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    }

    function startPolling() {
      if (pollingStarted || closed) {
        return;
      }
      pollingStarted = true;
      setStatus("polling");
      setMessage("Realtime socket unavailable. Polling dashboard snapshots.");
      void pollSnapshot();
    }

    function stopPolling() {
      pollingStarted = false;
      pollFailureCount = 0;
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      pollAbortController?.abort();
    }

    async function pollSnapshot() {
      if (closed || pollAbortController) {
        return;
      }
      pollAbortController = new AbortController();
      try {
        const response = await fetch("/dashboard-api/dashboard/realtime-snapshot", {
          cache: "no-store",
          signal: pollAbortController.signal,
        });
        if (!response.ok) {
          throw new Error(`snapshot request failed with status ${response.status}`);
        }
        onSnapshotRef.current((await response.json()) as DashboardRealtimeSnapshot);
        pollFailureCount = 0;
        setStatus("polling");
        setMessage("Realtime socket unavailable. Polling dashboard snapshots.");
      } catch (error) {
        if (closed || pollAbortController.signal.aborted) {
          return;
        }
        pollFailureCount += 1;
        setStatus("offline");
        setMessage(error instanceof Error ? error.message : "Realtime polling failed.");
      } finally {
        pollAbortController = null;
        if (!closed && pollingStarted) {
          const delay = Math.min(
            POLL_INTERVAL_MS * 2 ** pollFailureCount,
            MAX_POLL_DELAY_MS,
          );
          pollTimer = setTimeout(() => {
            pollTimer = null;
            void pollSnapshot();
          }, delay);
        }
      }
    }

    void connect();

    return () => {
      closed = true;
      if (pollTimer) {
        clearTimeout(pollTimer);
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      pollAbortController?.abort();
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close(1000, "component unmounted");
      }
    };
  }, [enabled]);

  return { status, message };
}
