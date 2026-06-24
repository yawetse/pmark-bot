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
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var theme=localStorage.getItem("codex-poly-bot-theme");if(theme==="light"||theme==="dark"){document.documentElement.dataset.theme=theme}}catch(e){}`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
