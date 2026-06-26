import "./globals.css";
import type { ReactNode } from "react";

import { TelemetryProvider } from "@/components/observability/telemetry-provider";

export const metadata = {
  title: "codex-poly-bot",
  description: "Operational dashboard for codex-poly-bot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <TelemetryProvider />
        {children}
      </body>
    </html>
  );
}
