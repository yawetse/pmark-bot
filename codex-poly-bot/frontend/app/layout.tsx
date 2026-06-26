import "./globals.css";
import type { ReactNode } from "react";

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
        {children}
      </body>
    </html>
  );
}
