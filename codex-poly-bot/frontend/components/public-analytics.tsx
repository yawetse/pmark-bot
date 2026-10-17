"use client";

import { useEffect } from "react";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * Load Analytics only on the explicitly public pages. The matching GA4 stream
 * must have Enhanced Measurement browser-history pageviews disabled; that
 * setting can otherwise track later client-side navigation into /dashboard.
 */
export function PublicAnalytics({
  measurementId,
  path,
  title,
}: {
  measurementId: string;
  path: "/" | "/story";
  title: string;
}) {
  useEffect(() => {
    if (!/^G-[A-Z0-9]+$/.test(measurementId)) return;

    window.dataLayer ??= [];
    window.gtag ??= function gtag(..._args: unknown[]) {
      window.dataLayer?.push(arguments);
    };

    if (!document.querySelector("script[data-niles-public-analytics]")) {
      window.gtag("js", new Date());
      window.gtag("config", measurementId, {
        send_page_view: false,
        page_location: `https://nilesagent.com${path}`,
        page_referrer: "",
        allow_google_signals: false,
        allow_ad_personalization_signals: false,
      });

      const script = document.createElement("script");
      script.async = true;
      script.dataset.nilesPublicAnalytics = "";
      script.src = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`;
      document.head.append(script);
    }

    window.gtag("event", "page_view", {
      page_location: `https://nilesagent.com${path}`,
      page_path: path,
      page_title: title,
      page_referrer: "",
    });
  }, [measurementId, path, title]);

  return null;
}
