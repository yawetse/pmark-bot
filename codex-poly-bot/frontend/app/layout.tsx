import "./globals.css";
import type { ReactNode } from "react";

import { TelemetryProvider } from "@/components/observability/telemetry-provider";

export const metadata = {
  title: "niles",
  description: "Operational dashboard for niles",
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
