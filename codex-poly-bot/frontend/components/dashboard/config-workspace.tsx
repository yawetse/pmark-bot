"use client";

import { useState } from "react";

import { ConfigControls } from "@/components/dashboard/config-controls";
import type { ConfigSnapshot } from "@/components/dashboard/config-controls";
import { FundingControls } from "@/components/dashboard/funding-controls";

export function ConfigWorkspace({
  initialSnapshot,
  loadError,
}: {
  initialSnapshot?: ConfigSnapshot;
  loadError?: string;
}) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);

  return (
    <div className="config-main-stack">
      {snapshot ? (
        <FundingControls
          initialSnapshot={snapshot}
          key={`funding-${snapshot.version}`}
          onSnapshotChange={setSnapshot}
        />
      ) : null}
      <ConfigControls
        initialSnapshot={snapshot}
        key={`config-${snapshot?.version ?? "unavailable"}`}
        loadError={loadError}
        onSnapshotChange={setSnapshot}
      />
    </div>
  );
}
