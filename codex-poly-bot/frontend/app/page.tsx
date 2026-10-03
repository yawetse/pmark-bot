import type { Metadata } from "next";

import { PublicProductLanding } from "@/components/product-story/product-landing";

// REQ: REQ-UI-002, REQ-UI-023

export const metadata: Metadata = {
  title: "niles | Controlled market automation",
  description:
    "See how niles finds, evaluates, gates, and manages prediction-market and stock trades.",
};

export default function HomePage() {
  return <PublicProductLanding />;
}
